#!/usr/bin/env python3
"""Public synthetic mbox -> native C# writer -> independent libpst MIME digest test.

Only counts and source-authored SHA256 comparisons are printed. No message content
is released or uploadable; this runs in a disposable public GitHub runner.
"""
from __future__ import annotations
from collections import Counter
from email import policy
from email.parser import BytesParser
import hashlib
import json
import mailbox
from pathlib import Path
import sys

def digest(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()

def inventory(messages):
    visible: Counter[str] = Counter()
    inline: Counter[str] = Counter()
    embedded = 0
    parse_defects = 0
    for msg in messages:
        for part in msg.walk():
            parse_defects += len(part.defects)
            if part.get_content_type() == "message/rfc822":
                embedded += 1
            if part.is_multipart():
                continue
            blob = part.get_payload(decode=True)
            if blob is None:
                continue
            disp = part.get_content_disposition()
            if disp == "attachment" and part.get_content_type() != "message/rfc822":
                visible[digest(blob)] += 1
            elif disp == "inline" and part.get("Content-ID"):
                inline[digest(blob)] += 1
    return visible, inline, embedded, parse_defects

def main() -> int:
    if len(sys.argv) != 3:
        return 2
    source = Path(sys.argv[1])
    result_dir = Path(sys.argv[2])
    src_messages = list(mailbox.mbox(source, create=False))
    result_files = list(result_dir.rglob("*.eml"))
    recovered = [BytesParser(policy=policy.default).parsebytes(p.read_bytes())
                 for p in result_files]
    sv, si, se, sd = inventory(src_messages)
    rv, ri, re, rd = inventory(recovered)
    result = {
        "schema": "public-csharp-attachment-digest/v1",
        "source_message_count": len(src_messages),
        "readpst_eml_count": len(result_files),
        "source_visible_occurrences": sum(sv.values()),
        "recovered_visible_occurrences": sum(rv.values()),
        "source_inline_cid_occurrences": sum(si.values()),
        "recovered_inline_cid_occurrences": sum(ri.values()),
        "source_embedded_rfc822_parts": se,
        "recovered_embedded_rfc822_parts": re,
        "source_mime_defects": sd,
        "recovered_mime_defects": rd,
        "visible_sha256_multiset_equal": sv == rv,
        "inline_sha256_multiset_equal": si == ri,
        "scope": "synthetic-known-MIME-only-not-full-MAPI",
    }
    print(json.dumps(result, sort_keys=True))
    # Hard fail if known authored text file attachments vanish or change bytes.
    if len(src_messages) != len(result_files) or not sv or sv != rv:
        return 3
    # Inline equality is diagnostic, not a qualified gate until converter
    # and independent reader CID representation is independently grounded.
    return 0

if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError, TypeError):
        print("PUBLIC_CSHARP_ATTACHMENT_VERIFIER_BLOCKED", file=sys.stderr)
        raise SystemExit(1)
