#!/usr/bin/env python3
"""Independent libpst readpst differential on published, digest-pinned fixtures.

All readpst input and converted output stays in a temporary runner workdir.
No message, attachment, filename, or raw native stderr is logged.
"""
from __future__ import annotations
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

from probe_public_pst import FIXTURES, get_bytes, verify_bytes


def main() -> int:
    reader = shutil.which("readpst")
    if reader is None:
        raise RuntimeError("readpst is unavailable")
    rows = []
    with tempfile.TemporaryDirectory(prefix="public-pst-second-oracle-") as scratch:
        root = Path(scratch)
        for i, (name, (digest, size, version)) in enumerate(FIXTURES.items()):
            data = get_bytes(name, size)
            verify_bytes(data, digest, size, version)
            source = root / ("source-" + str(i) + ".pst")
            source.write_bytes(data)
            output = root / ("extract-" + str(i))
            output.mkdir(mode=0o700)
            try:
                process = subprocess.run(
                    [reader, "-q", "-e", "-o", str(output), str(source)],
                    stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
                    timeout=25, check=False,
                )
                status = "EXIT0" if process.returncode == 0 else "NONZERO"
                exit_code = process.returncode
                diagnostics = bool(process.stderr.strip())
            except subprocess.TimeoutExpired:
                status, exit_code, diagnostics = "TIMEOUT", None, None
            # No extracted filename contents are released; derived email objects
            # are categorized only by suffix, with symlink outputs refused.
            children = list(output.rglob("*"))
            if any(x.is_symlink() for x in children):
                raise RuntimeError("unexpected output symlink")
            files = [x for x in children if x.is_file()]
            rows.append({
                "fixture": name, "readpst": status, "exit": exit_code,
                "stderr_present": diagnostics,
                "output_files": len(files),
                "eml_files": sum(x.suffix.lower() == ".eml" for x in files),
                "ics_files": sum(x.suffix.lower() == ".ics" for x in files),
                "vcf_files": sum(x.suffix.lower() == ".vcf" for x in files),
            })
            verify_bytes(source.read_bytes(), digest, size, version)
            source.unlink()
    print(json.dumps({"schema": "public-pst-independent-libpst/v1", "cases": rows},
                     sort_keys=True))
    return 2 if any(x["readpst"] == "TIMEOUT" for x in rows) else 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError, RuntimeError) as error:
        print(f"LIBPST_DIFFERENTIAL_BLOCKED {type(error).__name__}", file=sys.stderr)
        raise SystemExit(1)
