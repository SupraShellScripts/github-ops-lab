#!/usr/bin/env python3
"""Derive sanitized DNS/DoT state-machine candidate metadata from FRITZ!OS.

This scanner intentionally emits identifiers, hashes, relationships, and normalized
signatures only. It does not copy firmware source lines or raw source files.
"""
from __future__ import annotations

import argparse
import collections
import hashlib
import json
import pathlib
import re
from typing import Iterable

TARGETS = [
    "usr/www/avm/internet/dnsserver.lua",
    "usr/www/avm/internet/dnsserver.js",
    "usr/www/avm/js3/data/dnsserver.data.js",
    "usr/www/avm/internet/dyn_dns.lua",
    "usr/www/avm/js3/views/internet/access/dyndns.js",
    "usr/www/avm/js3/views/internet/access/dyndns.model.js",
]

KEYWORDS = (
    "dns", "dot", "fqdn", "resolver", "nameserver", "server", "strict",
    "fallback", "ipv4", "ipv6", "dyndns", "dynamic", "rebind", "udp",
)

IDENT_RE = re.compile(r"[A-Za-z_$][A-Za-z0-9_$.-]{1,95}")
STRING_RE = re.compile(r"([\"'])([^\"'\r\n]{1,160})\1")
CONTROL_RE = re.compile(r"\bui(?:View|Edit|Show|Enable|Disable|Select|Input|Text|Btn|Button|Check|Radio)?[A-Za-z0-9_]{2,96}\b")
ASSIGN_RE = re.compile(r"(?:\blocal\s+|\bconst\s+|\blet\s+|\bvar\s+)?([A-Za-z_$][A-Za-z0-9_$.-]{1,95})\s*=")
FUNCTION_RE = re.compile(r"(?:\bfunction\s+([A-Za-z_$][A-Za-z0-9_$.:]{1,95})|([A-Za-z_$][A-Za-z0-9_$.-]{1,95})\s*=\s*function\b)")
CALL_RE = re.compile(r"\b([A-Za-z_$][A-Za-z0-9_$.:]{1,95})\s*\(")
HTTP_RE = re.compile(r"\b(GET|POST|PUT|PATCH|DELETE)\b", re.IGNORECASE)
GUARD_RE = re.compile(r"\b(?:if|elseif)\b|\bif\s*\(", re.IGNORECASE)
OP_RE = re.compile(r"===|!==|==|!=|<=|>=|&&|\|\||\band\b|\bor\b|\bnot\b|[<>!]")
SAFE_TOKEN_RE = re.compile(r"^[A-Za-z0-9_./:{}?&=%+@-]{2,128}$")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", "replace")).hexdigest()


def contains_keyword(value: str) -> bool:
    lower = value.lower()
    return any(keyword in lower for keyword in KEYWORDS)


def identifiers(text: str) -> list[str]:
    return sorted(set(IDENT_RE.findall(text)))


def safe_strings(text: str) -> list[str]:
    values: set[str] = set()
    for match in STRING_RE.finditer(text):
        value = match.group(2).strip()
        if not SAFE_TOKEN_RE.match(value):
            continue
        if contains_keyword(value) or value.startswith("ui") or value.startswith("/api/") or value.endswith(".lua"):
            values.add(value)
    return sorted(values)


def normalized_guard(line: str) -> tuple[str, str, str]:
    ids = [item for item in identifiers(line) if item.lower() not in {"if", "elseif", "then", "true", "false", "nil", "null"}]
    ops = sorted(set(OP_RE.findall(line)))
    strings = [item for item in safe_strings(line) if contains_keyword(item) or item.startswith("ui")]
    return ",".join(sorted(set(ids))), ",".join(ops), ",".join(strings)


def enclosing_function(lines: list[str], index: int) -> str:
    for cursor in range(index, max(-1, index - 120), -1):
        match = FUNCTION_RE.search(lines[cursor])
        if match:
            return match.group(1) or match.group(2) or "<anonymous>"
    return "<top-level>"


def write_tsv(path: pathlib.Path, header: Iterable[str], rows: Iterable[Iterable[str]]) -> None:
    with path.open("w", encoding="utf-8") as handle:
        handle.write("\t".join(header) + "\n")
        for row in rows:
            handle.write("\t".join(str(value).replace("\t", " ") for value in row) + "\n")


def scan(root: pathlib.Path, output: pathlib.Path) -> None:
    output.mkdir(parents=True, exist_ok=True)

    file_rows: list[list[str]] = []
    identifier_rows: set[tuple[str, str, str]] = set()
    control_rows: set[tuple[str, str, str, str]] = set()
    guard_rows: set[tuple[str, str, str, str, str, str]] = set()
    assignment_rows: set[tuple[str, str, str]] = set()
    call_rows: set[tuple[str, str, str]] = set()
    request_rows: set[tuple[str, str, str, str, str]] = set()
    path_rows: set[tuple[str, str, str]] = set()
    pair_counts: collections.Counter[tuple[str, str, str]] = collections.Counter()

    for relative in TARGETS:
        path = root / relative
        if not path.is_file():
            continue
        data = path.read_bytes()
        text = data.decode("utf-8", "replace")
        lines = text.splitlines()
        file_rows.append([relative, str(len(data)), sha256_bytes(data), str(len(lines))])

        for line_number, line in enumerate(lines, start=1):
            line_ids = identifiers(line)
            interesting_ids = sorted({value for value in line_ids if contains_keyword(value)})
            for value in interesting_ids:
                identifier_rows.add((relative, value, sha256_text(line)))

            controls = sorted(set(CONTROL_RE.findall(line)))
            safe = safe_strings(line)
            for control in controls:
                related = sorted({value for value in line_ids if value != control and contains_keyword(value)})
                control_rows.add((relative, control, ",".join(related), sha256_text(line)))

            for match in ASSIGN_RE.finditer(line):
                target = match.group(1)
                if contains_keyword(target) or interesting_ids or controls:
                    assignment_rows.add((relative, target, sha256_text(line)))

            for match in CALL_RE.finditer(line):
                call = match.group(1)
                if contains_keyword(call) or interesting_ids or controls:
                    call_rows.add((relative, call, sha256_text(line)))

            if GUARD_RE.search(line) and (interesting_ids or controls or any(contains_keyword(value) for value in safe)):
                ids_sig, ops_sig, strings_sig = normalized_guard(line)
                guard_rows.add((relative, str(line_number), sha256_text(line), ids_sig, ops_sig, strings_sig))

            for value in safe:
                kind = "endpoint" if value.startswith("/") else "identifier"
                path_rows.add((relative, kind, value))

            # Candidate associations are deliberately weak static evidence: co-occurrence only.
            for control in controls:
                for value in interesting_ids:
                    pair_counts[(relative, control, value)] += 1

        # Request/save groups: derive function scope + identifiers from a bounded window.
        for index, line in enumerate(lines):
            lower = line.lower()
            if not any(token in lower for token in ("post", "put", "save", "apply", "data.lua", "query.lua")):
                continue
            window = "\n".join(lines[max(0, index - 8): min(len(lines), index + 9)])
            window_ids = sorted({value for value in identifiers(window) if contains_keyword(value)})
            window_strings = sorted({value for value in safe_strings(window) if contains_keyword(value) or value.startswith("ui") or value.startswith("/")})
            methods = sorted({value.upper() for value in HTTP_RE.findall(window)})
            function = enclosing_function(lines, index)
            if window_ids or window_strings:
                request_rows.add((relative, function, ",".join(methods) or "unknown", ",".join(window_ids), ",".join(window_strings)))

    write_tsv(output / "source-files.tsv", ["file", "bytes", "sha256", "lines"], sorted(file_rows))
    write_tsv(output / "identifiers.tsv", ["file", "identifier", "source_line_sha256"], sorted(identifier_rows))
    write_tsv(output / "ui-controls.tsv", ["file", "control", "related_dns_identifiers", "source_line_sha256"], sorted(control_rows))
    write_tsv(output / "guard-signatures.tsv", ["file", "line", "source_line_sha256", "identifiers", "operators", "safe_string_identifiers"], sorted(guard_rows))
    write_tsv(output / "assignment-targets.tsv", ["file", "target", "source_line_sha256"], sorted(assignment_rows))
    write_tsv(output / "call-targets.tsv", ["file", "call", "source_line_sha256"], sorted(call_rows))
    write_tsv(output / "request-groups.tsv", ["file", "enclosing_function", "http_methods", "dns_identifiers", "safe_string_identifiers"], sorted(request_rows))
    write_tsv(output / "path-identifiers.tsv", ["file", "kind", "value"], sorted(path_rows))
    write_tsv(output / "control-identifier-cooccurrence.tsv", ["file", "control", "identifier", "count"], [(*key, count) for key, count in sorted(pair_counts.items())])

    summary = {
        "schemaVersion": 1,
        "purpose": "sanitized-static-dns-state-machine-candidate-evidence",
        "sourceFilesObserved": len(file_rows),
        "identifierRows": len(identifier_rows),
        "uiControlRows": len(control_rows),
        "guardSignatureRows": len(guard_rows),
        "assignmentTargetRows": len(assignment_rows),
        "callTargetRows": len(call_rows),
        "requestGroupRows": len(request_rows),
        "pathIdentifierRows": len(path_rows),
        "controlIdentifierAssociations": len(pair_counts),
        "limitations": [
            "Static evidence only; does not authorize mutation.",
            "Guard signatures contain identifiers/operators/hashes, not source expressions.",
            "Control-to-identifier relationships are co-occurrence candidates until live-verified.",
            "No firmware/source payload is retained in this report."
        ],
    }
    (output / "summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    with (output / "summary.md").open("w", encoding="utf-8") as handle:
        handle.write("# FRITZ!OS 8.25 DNS/DoT state-machine candidate scan\n\n")
        handle.write("Sanitized static evidence only. No source text or firmware payload is retained.\n\n")
        for key, value in summary.items():
            if key in {"limitations", "purpose", "schemaVersion"}:
                continue
            handle.write(f"- {key}: {value}\n")
        handle.write("\nThis output is suitable for drafting experimental state variables/guards and selecting live read-only validation targets; it is not sufficient for enabling apply.\n")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=pathlib.Path)
    parser.add_argument("--output", required=True, type=pathlib.Path)
    args = parser.parse_args()
    scan(args.root, args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
