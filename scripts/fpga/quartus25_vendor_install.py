#!/usr/bin/env python3
"""Fail-closed, local-file-only admission of official Altera Quartus Lite 25.1.

Public-safe source. Never downloads installers, authenticates, or accepts terms implicitly.
Vendor files MUST remain outside Git/source/artifacts. No physical hardware operation.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import stat
import subprocess
import sys

FILES = (
    ("QuartusLiteSetup-25.1std.0.1129-linux.run", "ce0773469eacab5b7035c175484625f4ec3737d1", 900_000_000),
    ("cyclone-25.1std.0.1129.qdz", "835d2b1732549294eed625b692d044135499b5e8", 200_000_000),
)
REQUIRED_VERSION = ("Version 25.1std.0 Build 1129", "Lite Edition")
MIN_SCRATCH_BYTES = 25 * 1024**3


def hashes(path):
    sha1, sha256 = hashlib.sha1(), hashlib.sha256()
    with open(path, "rb") as f:
        while block := f.read(8 * 1024**2):
            sha1.update(block)
            sha256.update(block)
    return sha1.hexdigest(), sha256.hexdigest()


def observe(source, dest, hash_fn=hashes, disk_fn=shutil.disk_usage):
    source = Path(source)
    dest = Path(dest)
    base = {"schema": "quartus25-official-admission/v1",
            "target": "Quartus Prime Lite 25.1std.0 Build 1129 / EP4CE115F29C7",
            "compiler_executed": False, "eula_accepted_by_tool": False,
            "fit": "NOT_RUN", "timequest": "NOT_RUN", "hil": "NOT_RUN"}
    if source.is_symlink() or not source.is_dir():
        return dict(base, stage="INPUT_BLOCKED", reason="source directory not regular"), 2
    if dest.exists() or dest.is_symlink():
        return dict(base, stage="INPUT_BLOCKED", reason="destination must be new"), 2
    if platform.machine() not in ("x86_64", "AMD64"):
        return dict(base, stage="INPUT_BLOCKED", reason="requires Linux x86_64"), 2
    if platform.system() != "Linux":
        return dict(base, stage="INPUT_BLOCKED", reason="requires Linux"), 2
    result = []
    for name, sha1_expected, min_bytes in FILES:
        candidate = source / name
        try:
            mode = candidate.lstat().st_mode
            if not stat.S_ISREG(mode):
                return dict(base, stage="ARCHIVE_REJECTED", reason=name + ": not a regular file"), 3
            size = candidate.stat().st_size
            if size < min_bytes:
                return dict(base, stage="ARCHIVE_REJECTED", reason=name + ": undersized file"), 3
            actual_sha1, actual_sha256 = hash_fn(candidate)
        except FileNotFoundError:
            return dict(base, stage="ARCHIVE_MISSING", missing=name), 3
        if actual_sha1.lower() != sha1_expected:
            return dict(base, stage="ARCHIVE_REJECTED", reason=name + ": vendor SHA1 mismatch"), 3
        result.append({"name": name, "size_bytes": size, "sha1": actual_sha1,
                       "sha256": actual_sha256})
    parent = dest.parent
    if parent.is_symlink() or not parent.is_dir():
        return dict(base, stage="INPUT_BLOCKED", reason="destination parent not a directory"), 2
    disk = disk_fn(parent)
    if disk.free < MIN_SCRATCH_BYTES:
        return dict(base, stage="CAPACITY_BLOCKED", free_bytes=disk.free,
                    required_bytes=MIN_SCRATCH_BYTES), 3
    return dict(base, stage="ARCHIVES_VERIFIED_EULA_PENDING", archives=result,
                scratch_free_bytes=disk.free,
                installer_mode="official standalone Linux unattended",
                destination=str(dest.resolve(strict=False))), 0


def install(source, dest, approve, version_timeout=30, install_timeout=3600):
    receipt, status = observe(source, dest)
    if status:
        return receipt, status
    if not approve:
        return dict(receipt, stage="EULA_APPROVAL_REQUIRED",
                    reason="Operator must review terms and explicitly pass --accept-altera-eula"), 3
    dest = Path(dest)
    exe = Path(source) / FILES[0][0]
    command = [str(exe.resolve()), "--mode", "unattended",
               "--unattendedmodeui", "none",
               "--installdir", str(dest.resolve(strict=False)),
               "--accept_eula", "1"]
    try:
        p = subprocess.run(command, capture_output=True, text=True,
                           check=False, timeout=install_timeout)
    except (OSError, subprocess.TimeoutExpired) as e:
        return dict(receipt, stage="INSTALL_FAILED_UNCERTAIN_RESIDUE",
                    reason=type(e).__name__, eula_accepted_by_tool=True), 4
    if p.returncode != 0:
        return dict(receipt, stage="INSTALL_FAILED_UNCERTAIN_RESIDUE",
                    installer_exit_code=p.returncode, eula_accepted_by_tool=True,
                    installer_tail=(p.stdout + p.stderr)[-1200:]), 4
    tool = dest / "quartus" / "bin" / "quartus_sh"
    if not tool.is_file() or tool.is_symlink():
        return dict(receipt, stage="INSTALL_UNQUALIFIED",
                    reason="expected quartus_sh executable not found", eula_accepted_by_tool=True), 4
    try:
        v = subprocess.run([str(tool), "--version"], capture_output=True, text=True,
                           check=False, timeout=version_timeout)
    except (OSError, subprocess.TimeoutExpired) as e:
        return dict(receipt, stage="INSTALL_UNQUALIFIED", reason="version probe: " + type(e).__name__,
                    eula_accepted_by_tool=True), 4
    version = (v.stdout + v.stderr).strip()
    if v.returncode != 0 or not all(k in version for k in REQUIRED_VERSION):
        return dict(receipt, stage="INSTALL_UNQUALIFIED", reason="wrong version or edition",
                    quartus_version_excerpt=version[:500], eula_accepted_by_tool=True), 4
    return dict(receipt, stage="TOOL_IDENTITY_VERIFIED_DEVICE_UNCHECKED",
                quartus_version_excerpt=version[:500],
                tool_path=str(tool), eula_accepted_by_tool=True), 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("inspect", "install"))
    parser.add_argument("--archives", required=True, help="Private operator-controlled input directory")
    parser.add_argument("--destination", required=True, help="New install directory, e.g. /tmp/quartus-25.1")
    parser.add_argument("--accept-altera-eula", action="store_true",
                        help="Explicit acknowledgement that the operator reviewed/accepted the EULA")
    args = parser.parse_args()
    if args.command == "install":
        result, status = install(args.archives, args.destination, args.accept_altera_eula)
    else:
        result, status = observe(args.archives, args.destination)
    print(json.dumps(result, sort_keys=True, indent=2))
    return status


if __name__ == "__main__":
    raise SystemExit(main())
