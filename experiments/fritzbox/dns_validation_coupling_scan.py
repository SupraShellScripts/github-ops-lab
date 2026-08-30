#!/usr/bin/env python3
"""Emit sanitized DNS validation and native-save coupling evidence.

This pass is deliberately restricted to the exact stock dnsserver.lua resource. It
records validator/configuration call names, enclosing function, line number, call
hash, semantic argument identifiers, safe configuration-path tokens, and hashes of
quoted literals. It never retains source lines, raw regexes, arbitrary literals,
firmware payloads, credentials, or router data.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
import re

TARGET = "usr/www/avm/internet/dnsserver.lua"

CALLS = (
    "newval.is",
    "newval.ipv4",
    "newval.ipv6",
    "newval.not_empty",
    "newval.char_range_regex",
    "ip.read_from_post",
    "cmtable.add_var",
    "cmtable.commit",
)

SEMANTIC_TERMS = (
    "dns", "dot", "fqdn", "ipv4", "ipv6", "firstdns", "seconddns", "user_dns",
    "fallback", "edns", "dnscfg", "zero_not_allowed", "empty", "enabled", "strict",
    "udp", "post", "settings", "public", "use_user", "mac_and_hostname",
)

IDENT_RE = re.compile(r"[A-Za-z_$][A-Za-z0-9_$.:/-]{1,127}")
QUOTED_RE = re.compile(r"([\"'])(.*?)(?<!\\)\1", re.DOTALL)
NUMBER_BOOL_RE = re.compile(r"(?<![A-Za-z0-9_])(?:true|false|nil|null|-?\d+(?:\.\d+)?)(?![A-Za-z0-9_])")
FUNCTION_RE = re.compile(
    r"(?:\bfunction\s+([A-Za-z_$][A-Za-z0-9_$.:]{1,127})|"
    r"([A-Za-z_$][A-Za-z0-9_$.:]{1,127})\s*=\s*function\b)"
)
SAFE_PATH_RE = re.compile(r"^[A-Za-z0-9_./:{}?&=%+@-]{2,180}$")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", "replace")).hexdigest()


def semantic(value: str) -> bool:
    low = value.lower()
    return any(term in low for term in SEMANTIC_TERMS)


def find_balanced_calls(text: str, name: str):
    needle = name + "("
    start = 0
    while True:
        pos = text.find(needle, start)
        if pos < 0:
            return
        open_pos = pos + len(name)
        depth = 0
        quote = None
        escaped = False
        end = None
        limit = min(len(text), open_pos + 4096)
        for idx in range(open_pos, limit):
            ch = text[idx]
            if quote is not None:
                if escaped:
                    escaped = False
                elif ch == "\\":
                    escaped = True
                elif ch == quote:
                    quote = None
                continue
            if ch in ("'", '"'):
                quote = ch
                continue
            if ch == "(":
                depth += 1
            elif ch == ")":
                depth -= 1
                if depth == 0:
                    end = idx + 1
                    break
        if end is not None:
            yield pos, end, text[pos:end]
            start = end
        else:
            start = pos + len(needle)


def enclosing_function(lines: list[str], line_index: int) -> str:
    for cursor in range(line_index, max(-1, line_index - 180), -1):
        match = FUNCTION_RE.search(lines[cursor])
        if match:
            return match.group(1) or match.group(2) or "<anonymous>"
    return "<top-level>"


def nearest_guard_identifiers(lines: list[str], line_index: int) -> list[str]:
    for cursor in range(line_index, max(-1, line_index - 8), -1):
        stripped = lines[cursor].lstrip()
        if stripped.startswith("if ") or stripped.startswith("elseif "):
            return sorted({token for token in IDENT_RE.findall(lines[cursor]) if semantic(token)})[:80]
    return []


def sanitize_call(call_text: str):
    quoted_values = [match.group(2) for match in QUOTED_RE.finditer(call_text)]
    semantic_strings = sorted({
        value for value in quoted_values
        if SAFE_PATH_RE.fullmatch(value.strip()) and semantic(value.strip())
    })
    literal_hashes = sorted({sha256_text(value) for value in quoted_values})

    scrubbed = QUOTED_RE.sub(" ", call_text)
    identifiers = sorted({token for token in IDENT_RE.findall(scrubbed) if semantic(token)})
    constants = sorted(set(NUMBER_BOOL_RE.findall(scrubbed)))
    return identifiers[:120], semantic_strings[:120], constants[:80], literal_hashes[:120]


def write_tsv(path: pathlib.Path, header: tuple[str, ...], rows) -> None:
    with path.open("w", encoding="utf-8") as handle:
        handle.write("\t".join(header) + "\n")
        for row in rows:
            handle.write("\t".join(str(v).replace("\t", " ").replace("\n", " ") for v in row) + "\n")


def scan(root: pathlib.Path, output: pathlib.Path) -> None:
    path = root / TARGET
    if not path.is_file():
        raise SystemExit(f"missing exact target: {TARGET}")
    output.mkdir(parents=True, exist_ok=True)

    data = path.read_bytes()
    text = data.decode("utf-8", "replace")
    lines = text.splitlines()
    rows = []
    counts = {name: 0 for name in CALLS}
    functions = set()

    for name in CALLS:
        for start, end, call_text in find_balanced_calls(text, name):
            line_no = text.count("\n", 0, start) + 1
            line_index = max(0, line_no - 1)
            fn = enclosing_function(lines, line_index)
            identifiers, semantic_strings, constants, literal_hashes = sanitize_call(call_text)
            guards = nearest_guard_identifiers(lines, line_index)
            rows.append((
                TARGET,
                str(line_no),
                fn,
                name,
                sha256_text(call_text),
                ",".join(identifiers),
                ",".join(semantic_strings),
                ",".join(constants),
                ",".join(literal_hashes),
                ",".join(guards),
            ))
            counts[name] += 1
            functions.add(fn)

    rows.sort(key=lambda row: (int(row[1]), row[3], row[4]))
    write_tsv(
        output / "dns-validation-coupling-calls.tsv",
        (
            "file", "line", "enclosing_function", "call", "call_sha256",
            "semantic_argument_identifiers", "semantic_string_tokens", "scalar_constants",
            "quoted_literal_sha256", "nearest_guard_identifiers",
        ),
        rows,
    )

    do_save_rows = [row for row in rows if row[2] == "do_save"]
    val_prog_rows = [row for row in rows if row[2] == "val_prog"]
    do_save_calls = sorted({row[3] for row in do_save_rows})
    val_prog_calls = sorted({row[3] for row in val_prog_rows})
    do_save_semantics = sorted({
        token
        for row in do_save_rows
        for field in (row[5], row[6], row[9])
        for token in field.split(",")
        if token
    })
    val_prog_semantics = sorted({
        token
        for row in val_prog_rows
        for field in (row[5], row[6], row[9])
        for token in field.split(",")
        if token
    })

    summary = {
        "schemaVersion": 1,
        "purpose": "dns-validation-and-native-save-coupling",
        "targetFile": TARGET,
        "targetFileSha256": sha256_bytes(data),
        "callCounts": counts,
        "functionsObserved": sorted(functions),
        "valProgCalls": val_prog_calls,
        "valProgSemanticIdentifiers": val_prog_semantics,
        "doSaveCalls": do_save_calls,
        "doSaveSemanticIdentifiers": do_save_semantics,
        "sharedNativeCommitScopeObserved": (
            "cmtable.add_var" in do_save_calls and "cmtable.commit" in do_save_calls
        ),
        "semanticIndependenceProven": False,
        "limitations": [
            "Call argument identifiers and literal hashes are static evidence; they do not prove runtime branches or accepted values by themselves.",
            "Shared do_save/commit scope proves transaction grouping, not independent side-effect semantics for every field.",
            "No source lines, raw regexes, arbitrary literals, firmware payloads, credentials, or router data are retained.",
            "Static evidence does not authorize mutation."
        ],
        "decisionRule": (
            "Use this evidence to instantiate validation/normalization and shared-commit hypotheses. "
            "Any remaining unknown accepted-value, cross-field, or default semantics require one narrower "
            "exact-target proof or later controlled observation; do not broaden into generic reversing."
        ),
    }
    (output / "dns-validation-coupling-summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    md = [
        "# DNS validation and native-save coupling",
        "",
        "Sanitized exact-firmware evidence only.",
        "",
        f"- targetFileSha256: {summary['targetFileSha256']}",
        f"- valProgCalls: {', '.join(val_prog_calls)}",
        f"- doSaveCalls: {', '.join(do_save_calls)}",
        f"- sharedNativeCommitScopeObserved: {str(summary['sharedNativeCommitScopeObserved']).lower()}",
        "- semanticIndependenceProven: false",
    ]
    (output / "dns-validation-coupling-summary.md").write_text("\n".join(md) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=pathlib.Path)
    parser.add_argument("--output", required=True, type=pathlib.Path)
    args = parser.parse_args()
    if not args.root.is_dir():
        raise SystemExit(f"root is not a directory: {args.root}")
    scan(args.root.resolve(), args.output.resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
