#!/usr/bin/env python3
"""Bounded public-only PST reader -> MIME extraction experiment.

Only uses the commit- and SHA256-pinned published fixtures from probe_public_pst.
Does not log, upload, or retain mail bodies, filenames, addresses or attachments.
Native tool exit is NOT proof of completeness; no MAPI gold verdict is asserted.
"""
from __future__ import annotations

import argparse
from collections import Counter
from email import policy
from email.message import EmailMessage
from email.parser import BytesParser
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

from probe_public_pst import FIXTURES, get_bytes, verify_bytes, classify_native_exit

MAX_FILES = 300
MAX_OUTPUT_BYTES = 32 * 1024 * 1024
MAX_ITEM_BYTES = 8 * 1024 * 1024


def scan_files(root: Path) -> list[Path]:
    if not root.exists():
        return []
    if root.is_symlink() or not root.is_dir():
        raise ValueError("unsafe output root")
    result = []
    byte_count = 0
    for item in root.rglob("*"):
        if item.is_symlink():
            raise ValueError("symlink in native output")
        if item.is_file():
            if not item.resolve().is_relative_to(root.resolve()):
                raise ValueError("output escaped sandbox")
            result.append(item)
            byte_count += item.stat().st_size
            if len(result) > MAX_FILES or byte_count > MAX_OUTPUT_BYTES:
                raise ValueError("output exceeds file/byte budget")
    return result


def mime_counts(paths: list[Path]) -> dict[str, int]:
    counts: Counter[str] = Counter()
    digests: set[str] = set()
    parser = BytesParser(policy=policy.default)
    for path in paths:
        if path.suffix.lower() != ".eml":
            continue
        if path.stat().st_size > MAX_ITEM_BYTES:
            counts["oversize_eml"] += 1
            continue
        try:
            message = parser.parsebytes(path.read_bytes())
            counts["eml_parsed"] += 1
            for part in message.walk():
                counts["parse_defects"] += len(part.defects)
                ctype = part.get_content_type().lower()
                if ctype == "message/rfc822":
                    counts["embedded_rfc822_parts"] += 1
                if part.is_multipart():
                    continue
                disposition = part.get_content_disposition()
                if ctype == "text/plain":
                    counts["plain_parts"] += 1
                if ctype == "text/html":
                    counts["html_parts"] += 1
                if part.get("Content-ID"):
                    counts["cid_parts"] += 1
                if disposition == "attachment" or (
                    disposition == "inline" and part.get("Content-ID")
                ):
                    counts["attachment_occurrences"] += 1
                    payload = part.get_payload(decode=True)
                    if payload is None:
                        counts["attachment_unavailable"] += 1
                    else:
                        digests.add(hashlib.sha256(payload).hexdigest())
        except (OSError, ValueError, TypeError, UnicodeError):
            counts["eml_parse_errors"] += 1
    counts["distinct_attachment_payloads"] = len(digests)
    return dict(sorted(counts.items()))


def native(argv: list[str]) -> tuple[str, int | None, list[str]]:
    try:
        proc = subprocess.run(
            argv, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
            timeout=30, check=False,
        )
        state, diagnostic_tags = classify_native_exit(proc.returncode, proc.stderr)
        return state, proc.returncode, diagnostic_tags
    except subprocess.TimeoutExpired:
        return "TIMEOUT", None, []


def selftest() -> None:
    with tempfile.TemporaryDirectory(prefix="public-mime-selftest-") as tmp:
        root = Path(tmp)
        mail = EmailMessage()
        mail["Subject"] = "synthetic"
        mail["From"] = "fixture@example.invalid"
        mail["To"] = "test@example.invalid"
        mail.set_content("Synthetic English Deutsch ไทย")
        mail.add_alternative("<p>synthetic</p>", subtype="html")
        for name in ("alpha.bin", "beta.bin"):
            mail.add_attachment(b"same-payload", maintype="application",
                                subtype="octet-stream", filename=name)
        (root / "synthetic.eml").write_bytes(mail.as_bytes())
        d = mime_counts(scan_files(root))
        assert d["eml_parsed"] == 1, d
        assert d["plain_parts"] == 1 and d["html_parts"] == 1, d
        assert d["attachment_occurrences"] == 2, d
        assert d["distinct_attachment_payloads"] == 1, d
        (root / "unsafe-link").symlink_to(root / "synthetic.eml")
        try:
            scan_files(root)
        except ValueError:
            pass
        else:
            raise AssertionError("symlink negative control passed")
    assert classify_native_exit(0, b"unable to retrieve a source item")[0] == "EXIT0_WITH_DIAGNOSTICS"
    print("MIME_BAKEOFF_SELFTEST_PASS synthetic multipart, duplicate occurrence, symlink and exit0 diagnostic")


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--selftest", action="store_true")
    p.add_argument("--run", action="store_true")
    args = p.parse_args()
    if args.selftest:
        selftest()
    if not args.run:
        return 0 if args.selftest else p.error("use --selftest or --run")
    reader, exporter = shutil.which("readpst"), shutil.which("pffexport")
    if not reader or not exporter:
        print("MIME_BAKEOFF_UNAVAILABLE_REQUIRED_NATIVE_TOOL", file=sys.stderr)
        return 2
    rows: list[dict[str, object]] = []
    with tempfile.TemporaryDirectory(prefix="public-pst-mime-") as tmp:
        base = Path(tmp)
        for i, (name, (digest, size, version)) in enumerate(FIXTURES.items()):
            data = get_bytes(name, size)
            verify_bytes(data, digest, size, version)
            source = base / ("source-" + str(i) + ".pst")
            source.write_bytes(data)
            read_out = base / ("readpst-" + str(i))
            read_out.mkdir(mode=0o700)
            pff_prefix = base / ("pff-" + str(i))
            read_state, read_exit, read_tags = native(
                [reader, "-q", "-e", "-o", str(read_out), str(source)]
            )
            pff_state, pff_exit, pff_tags = native(
                [exporter, "-v", "-m", "items", "-t", str(pff_prefix), str(source)]
            )
            read_files = scan_files(read_out)
            pff_files = [
                item for folder in base.glob(pff_prefix.name + ".*")
                if folder.is_dir() for item in scan_files(folder)
            ]
            row = {
                "fixture": name, "pst_version": version, "source_sha256_verified": True,
                "readpst_status": read_state, "readpst_exit": read_exit,
                "readpst_diagnostic_tags": read_tags,
                "pffexport_items_status": pff_state, "pffexport_exit": pff_exit,
                "pffexport_diagnostic_tags": pff_tags,
                "readpst_files": len(read_files), "pffexport_files": len(pff_files),
                "readpst_eml": sum(p.suffix.lower() == ".eml" for p in read_files),
                "readpst_ics": sum(p.suffix.lower() == ".ics" for p in read_files),
                "readpst_vcf": sum(p.suffix.lower() == ".vcf" for p in read_files),
                "mime_derived": mime_counts(read_files),
                "native_property_completeness": "UNVERIFIED",
            }
            verify_bytes(source.read_bytes(), digest, size, version)
            rows.append(row)
            # Each source's derived material is disposable; never committed or uploaded.
            shutil.rmtree(read_out)
            for folder in base.glob(pff_prefix.name + ".*"):
                if folder.is_dir():
                    shutil.rmtree(folder)
            source.unlink()
    print(json.dumps({
        "schema": "public-pst-mime-bakeoff/v1",
        "source_fixture_revision": "857470dfc1ea8c4d03d4d93603401a05c2c8e307",
        "qualification": "EXPLORATORY_NOT_MAPI_GOLD",
        "cases": rows,
    }, sort_keys=True, ensure_ascii=True))
    if any(row["readpst_status"] == "TIMEOUT" or row["pffexport_items_status"] == "TIMEOUT"
           for row in rows):
        return 3
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError, RuntimeError, AssertionError) as err:
        # Type only; never emit raw document data, filenames, message headers or paths.
        print("PUBLIC_MIME_BAKEOFF_BLOCKED " + type(err).__name__, file=sys.stderr)
        raise SystemExit(1)
