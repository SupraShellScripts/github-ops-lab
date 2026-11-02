#!/usr/bin/env python3
"""Public-only reverse interoperability: libpst EML -> mbox -> C# PST -> independent readers.

Only known published and SHA256-pinned sources are fetched. All input and
output bytes remain in disposable runner tempdirs. No subjects, addresses,
bodies, filenames of recovered items, or derived private hashes printed.
"""
from __future__ import annotations
import collections
from email import policy
from email.parser import BytesParser
import hashlib
import json
import mailbox
from pathlib import Path
import subprocess
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from probe_public_pst import FIXTURES, get_bytes, verify_bytes

CASES = ("pstsdk-sample1.pst", "pstsdk-submessage.pst", "pstd-inline-cid.pst")
PARSER = BytesParser(policy=policy.default)

def command(args: list[str], timeout: int = 40) -> tuple[int | None, bytes]:
    try:
        result = subprocess.run(args, check=False, stdout=subprocess.PIPE,
                                stderr=subprocess.DEVNULL, timeout=timeout)
        return result.returncode, result.stdout[:8192]
    except subprocess.TimeoutExpired:
        return None, b""

def collect_eml(root: Path):
    return [PARSER.parsebytes(p.read_bytes()) for p in sorted(root.rglob("*.eml"))]

def inventory(messages):
    """Compare the same source-observable properties, not MAPI-unrepresentable data."""
    fields: dict[str, collections.Counter[str]] = {
        "message-id": collections.Counter(),
        "subject": collections.Counter(),
        "from": collections.Counter(),
        "to": collections.Counter(),
        "cc": collections.Counter(),
        "bcc": collections.Counter(),
        "plain": collections.Counter(),
        "html": collections.Counter(),
        "binary": collections.Counter(),
    }
    defects = 0
    embedded = 0
    for m in messages:
        for field in ("message-id", "subject", "from", "to", "cc", "bcc"):
            val = str(m.get(field) or "").strip()
            if val:
                fields[field][hashlib.sha256(val.encode("utf-8")).hexdigest()] += 1
        for part in m.walk():
            defects += len(part.defects)
            ct = part.get_content_type()
            if ct == "message/rfc822":
                embedded += 1
            if part.is_multipart():
                continue
            raw = part.get_payload(decode=True)
            if raw is None:
                continue
            disp = part.get_content_disposition()
            if disp == "attachment" or ct not in ("text/plain", "text/html"):
                key = "binary"
            elif ct == "text/plain":
                key = "plain"
            else:
                key = "html"
            if key != "binary":
                # Normalize line endings, not characters, before byte hashing.
                raw = raw.replace(b"\r\n", b"\n").replace(b"\r", b"\n")
            fields[key][hashlib.sha256(raw).hexdigest()] += 1
    return fields, {"messages": len(messages), "mime_defects": defects, "embedded_rfc822": embedded}

def compare(source, output):
    left, lmeta = inventory(source)
    right, rmeta = inventory(output)
    equal = {k: left[k] == right[k] for k in left}
    return {
        "source_messages": lmeta["messages"],
        "rewrite_messages": rmeta["messages"],
        "source_embedded_rfc822": lmeta["embedded_rfc822"],
        "rewrite_embedded_rfc822": rmeta["embedded_rfc822"],
        "source_mime_defects": lmeta["mime_defects"],
        "rewrite_mime_defects": rmeta["mime_defects"],
        "source_binary_occurrences": sum(left["binary"].values()),
        "rewrite_binary_occurrences": sum(right["binary"].values()),
        "source_plain_parts": sum(left["plain"].values()),
        "rewrite_plain_parts": sum(right["plain"].values()),
        "field_multiset_equal": equal,
        "comparable_MAPI_properties": "NOT_ALL",
        "native_source_object_completeness": "UNVERIFIED"
    }

def check_csharp(path: Path, probe: Path):
    code, stdout = command(["dotnet", str(probe), str(path)], 20)
    if code != 0:
        return "PROCESS_FAILED"
    try:
        d = json.loads(stdout)
        return str(d.get("status", "UNKNOWN"))
    except (ValueError, TypeError):
        return "INVALID_PROBE_RESULT"

def main() -> int:
    if len(sys.argv) != 3:
        return 2
    cli = Path(sys.argv[1]).resolve()
    probe = Path(sys.argv[2]).resolve()
    results = []
    with tempfile.TemporaryDirectory(prefix="public-rewrite-interoperability-") as tmp:
        home = Path(tmp)
        for ix, name in enumerate(CASES):
            sha, size, version = FIXTURES[name]
            data = get_bytes(name, size)
            verify_bytes(data, sha, size, version)
            src = home / ("pinned-" + str(ix) + ".pst")
            src.write_bytes(data)
            original = home / ("unpacked-" + str(ix))
            original.mkdir()
            oexit, _ = command(["readpst", "-q", "-e", "-o", str(original), str(src)])
            before = collect_eml(original)
            record = {"fixture": name, "source_sha256_verified": True,
                      "source_version": version, "source_readpst_exit": oexit,
                      "source_csharp": check_csharp(src, probe)}
            if oexit != 0 or not before:
                record["status"] = "SOURCE_READ_UNSUPPORTED"
                results.append(record)
                continue
            # Build exact synthetic/redistributable mail reconstruction from libpst EML.
            mbox_path = home / ("converted-" + str(ix) + ".mbox")
            mb = mailbox.mbox(mbox_path, create=True)
            try:
                mb.lock()
                for msg in before:
                    mb.add(msg)
                mb.flush()
            finally:
                mb.unlock()
                mb.close()
            if mbox_path.stat().st_size > 2_000_000:
                record["status"] = "MBOX_SIZE_LIMIT"
                results.append(record)
                continue
            config = {"outputs": [{"name": "RoundtripPublic", "maxSizeMB": 100,
                                  "folderMapping": "mirror",
                                  "sources": [{"path": str(mbox_path), "type": "mbox"}]}]}
            cfg = home / ("config-" + str(ix) + ".json")
            cfg.write_text(json.dumps(config), encoding="utf-8")
            out = home / ("pst-" + str(ix))
            out.mkdir()
            exit_convert, _ = command(["dotnet", str(cli), "convert",
                                       "--config", str(cfg), "--output", str(out)], 100)
            artifacts = list(out.rglob("*.pst"))
            record["conversion_exit"] = exit_convert
            record["generated_psts"] = len(artifacts)
            if exit_convert != 0 or len(artifacts) != 1:
                record["status"] = "WRITER_UNAVAILABLE"
                results.append(record)
                continue
            newpst = artifacts[0]
            if newpst.stat().st_size > 16_000_000:
                record["status"] = "WRITTEN_PST_SIZE_LIMIT"
                results.append(record)
                continue
            record["pffinfo_exit"], _ = command(["pffinfo", str(newpst)])
            record["rewrite_csharp"] = check_csharp(newpst, probe)
            regenerated = home / ("reexport-" + str(ix))
            regenerated.mkdir()
            record["rewrite_readpst_exit"], _ = command(
                ["readpst", "-q", "-e", "-o", str(regenerated), str(newpst)]
            )
            after = collect_eml(regenerated)
            record["semantic"] = compare(before, after)
            record["status"] = (
                "REWRITTEN_SEMANTIC_COMPARISON_RECORDED"
                if record["pffinfo_exit"] == 0 and record["rewrite_readpst_exit"] == 0
                else "REWRITTEN_READER_FAILED"
            )
            verify_bytes(src.read_bytes(), sha, size, version)
            results.append(record)
    print(json.dumps({
        "schema": "public-pst-cross-reader-rewrite/v1",
        "source_revision": "857470dfc1ea8c4d03d4d93603401a05c2c8e307",
        "scope": "public-synthetic-only; source-MIME-derived; lossy-MAPI-risk",
        "cases": results
    }, sort_keys=True))
    return 0 if all(c["status"] == "REWRITTEN_SEMANTIC_COMPARISON_RECORDED" for c in results) else 3

if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError, TypeError, KeyError):
        print("PUBLIC_REWRITE_INTEROP_BLOCKED", file=sys.stderr)
        raise SystemExit(1)
