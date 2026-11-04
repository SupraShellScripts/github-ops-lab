#!/usr/bin/env python3
"""Inspect *official complete TAR* Quartus 25.1 input without extracting or executing.

Original public-safe verifier. Real vendor bytes stay in private executor-local scratch.
No installer, EULA, network, programming or public artifact side effects.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import stat
import tarfile

TAR_NAME = "Quartus-lite-25.1std.0.1129-linux.tar"
TAR_SHA1 = "833c96461eb55e0124f358c8ec9322ba1fbd5286"
TAR_MIN_BYTES = 8_000_000_000
QDZ_NAME = "cyclone-25.1std.0.1129.qdz"
QDZ_SHA1 = "835d2b1732549294eed625b692d044135499b5e8"
QDZ_MIN_BYTES = 400_000_000
# Official page states 40.10 GB combined archived/extracted/installed, plus workspace.
MIN_FREE_BYTES = 55 * 1024**3


def digest_file(path):
    sha1 = hashlib.sha1()
    sha256 = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024**2), b""):
            sha1.update(block)
            sha256.update(block)
    return sha1.hexdigest(), sha256.hexdigest()


def member_status(archive_path):
    """Inspect metadata only, fail closed on unsafe paths and links."""
    count = 0
    setup_candidates = set()
    unsafe = []
    with tarfile.open(archive_path, mode="r|") as tar:
        for info in tar:
            count += 1
            name = info.name
            rel = PurePosixPath(name)
            if (not name or rel.is_absolute()
                    or ".." in rel.parts or "\\" in name
                    or not (info.isfile() or info.isdir())):
                unsafe.append(name[:160])
            if info.isfile() and rel.name == "setup.sh":
                setup_candidates.add(name)
            if count > 100000:
                raise ValueError("unexpectedly large TAR file list")
    return {"member_count": count,
            "setup_candidates": sorted(setup_candidates),
            "unsafe_member_count": len(unsafe),
            "unsafe_examples": unsafe[:3]}


def observe(directory, *, hash_fn=digest_file, member_fn=member_status,
            disk_fn=shutil.disk_usage, min_tar_size=TAR_MIN_BYTES):
    base = {"schema": "quartus25-complete-tar-admission/v1",
            "target": "Quartus Prime Lite 25.1std.0 Build 1129 / Cyclone IV E",
            "vendor_bytes_published": False, "archive_extracted": False,
            "installer_executed": False, "eula_accepted": False,
            "quartus_compile": "NOT_RUN", "timequest": "NOT_RUN"}
    directory = Path(directory)
    if not directory.is_dir() or directory.is_symlink():
        return dict(base, stage="INPUT_BLOCKED", reason="directory unavailable or symlink"), 2
    items = []
    for name, expected_sha1, min_size in [
        (TAR_NAME, TAR_SHA1, min_tar_size),
        (QDZ_NAME, QDZ_SHA1, QDZ_MIN_BYTES),
    ]:
        src = directory / name
        try:
            stat_info = src.lstat()
        except FileNotFoundError:
            return dict(base, stage="ARCHIVE_MISSING", expected_file=name), 3
        if not stat.S_ISREG(stat_info.st_mode) or stat_info.st_size < min_size:
            return dict(base, stage="ARCHIVE_REJECTED", reason=name + ": type or size"), 3
        actual_sha1, sha256 = hash_fn(src)
        if actual_sha1 != expected_sha1:
            return dict(base, stage="ARCHIVE_REJECTED", reason=name + ": vendor SHA1 mismatch"), 3
        items.append({"name": name, "size_bytes": stat_info.st_size,
                      "sha1": actual_sha1, "sha256": sha256})
    try:
        manifest = member_fn(directory / TAR_NAME)
    except (tarfile.TarError, ValueError, OSError) as e:
        return dict(base, stage="TAR_METADATA_REJECTED", reason=type(e).__name__), 3
    if manifest["unsafe_member_count"] or not manifest["setup_candidates"]:
        return dict(base, stage="TAR_METADATA_REJECTED", manifest=manifest), 3
    free = disk_fn(directory).free
    if free < MIN_FREE_BYTES:
        return dict(base, stage="CAPACITY_BLOCKED",
                    free_bytes=free, required_bytes=MIN_FREE_BYTES), 3
    return dict(base, stage="TAR_AND_QDZ_VERIFIED_EULA_PENDING",
                artifacts=items, tar_metadata=manifest, free_bytes=free), 0


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--archives", required=True, help="private local directory with verified TAR and QDZ")
    a = p.parse_args()
    result, code = observe(a.archives)
    print(json.dumps(result, indent=2, sort_keys=True))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
