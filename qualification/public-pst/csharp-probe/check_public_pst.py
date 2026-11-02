#!/usr/bin/env python3
"""C# PSTFileFormat reader versus hash-pinned *published* PST fixtures.

Fetch only allowlisted public test PSTs into disposable files. Print metadata only.
No mail content, sender, subject, personal paths, hashes derived from private bytes.
"""
from __future__ import annotations
import json
from pathlib import Path
import subprocess
import sys
import tempfile
# Source file lives one directory above this nested probe.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from probe_public_pst import FIXTURES, get_bytes, verify_bytes

def probe(exe: Path, path: Path) -> dict:
    try:
        p = subprocess.run(["dotnet", str(exe), str(path)],
                           stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                           timeout=20, check=False)
        if p.returncode:
            return {"status": "PROBE_EXIT_NONZERO", "code": p.returncode}
        if len(p.stdout) > 4096:
            return {"status": "PROBE_OUTPUT_OVERFLOW"}
        result = json.loads(p.stdout)
        assert isinstance(result, dict)
        return {k: v for k, v in result.items()
                if k in ("status", "errorType", "folderCount",
                         "folderReportedItemCount", "notesRead",
                         "attachmentCount", "unsupportedNonMailFolders",
                         "nativeMAPICompleteness")}
    except subprocess.TimeoutExpired:
        return {"status": "TIMEOUT"}
    except (OSError, ValueError, AssertionError, TypeError):
        return {"status": "PROBE_PARSE_ERROR"}

def main() -> int:
    if len(sys.argv) != 2:
        return 2
    exe = Path(sys.argv[1]).resolve()
    rows = []
    with tempfile.TemporaryDirectory(prefix="public-csharp-pst-") as tmp:
        for i, (name, (digest, size, version)) in enumerate(FIXTURES.items()):
            source = Path(tmp) / ("source-" + str(i) + ".pst")
            blob = get_bytes(name, size)
            verify_bytes(blob, digest, size, version)
            source.write_bytes(blob)
            row = {"fixture": name, "source_sha256_verified": True,
                   "version": version, **probe(exe, source)}
            verify_bytes(source.read_bytes(), digest, size, version)
            rows.append(row)
            source.unlink()
    print(json.dumps({"schema": "public-csharp-pstfileformat/v1",
                      "qualification": "EXPLORATORY_NOT_ALL_MAPI_GOLD",
                      "cases": rows}, sort_keys=True))
    # Retain failure as evidence and avoid declaring the entire C# reader qualified.
    return 0 if any(row["status"] != "FAILED" for row in rows) else 3

if __name__ == "__main__":
    raise SystemExit(main())
