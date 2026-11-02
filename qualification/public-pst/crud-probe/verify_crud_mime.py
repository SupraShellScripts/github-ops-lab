#!/usr/bin/env python3
"""Verify known synthetic CRUD changes in independent readpst exports; no content printed."""
from email import policy
from email.parser import BytesParser
from pathlib import Path
import json
import sys
if len(sys.argv) != 2:
    sys.exit(2)
root = Path(sys.argv[1])
items = list(root.rglob("*.eml"))
parsed = [BytesParser(policy=policy.default).parsebytes(p.read_bytes()) for p in items]
subjects = [str(m.get("Subject") or "").strip() for m in parsed]
texts = []
for m in parsed:
    for part in m.walk():
        if part.get_content_type() == "text/plain" and part.get_content_disposition() != "attachment":
            raw = part.get_payload(decode=True)
            if raw:
                charset = part.get_content_charset() or "utf-8"
                texts.append(raw.decode(charset, errors="replace"))
expected = {"PST-CRUD-UPDATED", "PST-CRUD-ADDED"}
status = (
    len(items) == 2 and set(subjects) == expected
    and any("PST-CRUD-UPDATED-BODY" in s for s in texts)
    and any("PST-CRUD-ADDED-BODY" in s for s in texts)
)
print(json.dumps({"schema": "public-pst-crud-independent-mime/v1",
                  "passed": status, "eml_count": len(items),
                  "expected_update_present": "PST-CRUD-UPDATED" in subjects,
                  "expected_creation_present": "PST-CRUD-ADDED" in subjects,
                  "expected_body_update_present": any("PST-CRUD-UPDATED-BODY" in s for s in texts),
                  "expected_created_body_present": any("PST-CRUD-ADDED-BODY" in s for s in texts),
                  "staged_logical_deletion": len(items) == 2,
                  "physical_secure_erasure": "NOT_CLAIMED",
                  "full_MAPI_parity": "UNVERIFIED"},sort_keys=True))
sys.exit(0 if status else 3)
