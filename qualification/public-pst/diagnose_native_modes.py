#!/usr/bin/env python3
"""Bounded libpff mode failure-class diagnosis on three public test PSTs only.

This is public-from-birth. All output is whitelisted metadata; stderr/stdout
and extracted objects are never printed or retained.
"""
from __future__ import annotations
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile

from probe_public_pst import FIXTURES, get_bytes, verify_bytes

TARGETS = ("pstd-inline-cid.pst", "synth-basics.pst", "pstsdk-sample1.pst")
MODES = ("items", "recovered", "all")
# Whitelist function names, not arbitrary stderr lines or decoded mail data.
FUNCTION = re.compile(r"\b(?:libpff|libcdata|libfdata|libbfio|export_handle|pffinput)_[a-z0-9_]{3,95}\b")
ERROR_MARKERS = {
    "unable_recover": "unable to recover",
    "unable_export": "unable to export",
    "missing_index": "missing index",
    "unable_read": "unable to read",
    "unsupported": "unsupported",
    "already_exists": "already exists",
    "out_of_bounds": "out of bounds",
    "invalid_value": "invalid value",
    "invalid_range_list": "invalid range list",
    "missing_range_list": "missing range list",
    "unable_read_allocation": "unable to read allocation",
    "invalid_allocation": "invalid allocation",
    "unable_retrieve_unallocated": "unable to retrieve number of unallocated",
    "failed": "failed",
}


def main() -> int:
    exporter = shutil.which("pffexport")
    if not exporter:
        raise RuntimeError("MISSING_PFFEXPORT")
    results = []
    with tempfile.TemporaryDirectory(prefix="public-pst-mode-diagnose-") as work:
        for index, name in enumerate(TARGETS):
            digest, size, version = FIXTURES[name]
            data = get_bytes(name, size)
            verify_bytes(data, digest, size, version)
            source = Path(work) / ("store" + str(index) + ".pst")
            source.write_bytes(data)
            for mode in MODES:
                target = Path(work) / ("target-" + str(index) + "-" + mode)
                try:
                    process = subprocess.run(
                        [exporter, "-v", "-m", mode, "-t", str(target), str(source)],
                        stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, timeout=20,
                        check=False,
                    )
                    log = process.stderr[:65536].decode("utf-8", "replace")
                    row = {
                        "fixture": name, "mode": mode,
                        "exit": process.returncode,
                        "errors": [key for key, value in ERROR_MARKERS.items()
                                   if value in log.lower()],
                        "functions": sorted(set(FUNCTION.findall(log)))[:12],
                        "stderr_bytes": len(process.stderr),
                        "stderr_truncated": len(process.stderr) > 65536,
                    }
                except subprocess.TimeoutExpired:
                    row = {"fixture": name, "mode": mode, "exit": "TIMEOUT"}
                results.append(row)
            verify_bytes(source.read_bytes(), digest, size, version)
            source.unlink()
    print(json.dumps({"schema": "public-libpff-mode-diagnosis/v1", "cases": results},
                     sort_keys=True))
    # These two failures are not auto-normalized: diagnosis is evidence only.
    if any(r.get("exit") == "TIMEOUT" for r in results):
        return 2
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError, RuntimeError) as error:
        print(f"DIAGNOSIS_BLOCKED {type(error).__name__}", file=sys.stderr)
        raise SystemExit(1)
