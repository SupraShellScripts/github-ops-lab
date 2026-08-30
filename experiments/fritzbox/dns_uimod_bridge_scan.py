#!/usr/bin/env python3
"""Trace only the REST generic-API -> Uimod configuration bridge.

This is a structural sanitizer, not a source exporter. It examines the exact
firmware's api_generic/uimod Lua modules and emits only function names, call
identifiers, anchor names, line numbers/hashes, file hashes, and bounded identifier
sets. Source text and configuration values are never retained.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
import re

TARGETS = (
    "usr/rest_api/api_generic.lua",
    "usr/rest_api/uimod.lua",
)

ANCHORS = (
    "ui:set_webvar",
    "ui:get_module",
    "ui.transaction",
    "set_webvar",
    "get_module",
    "transaction",
    "Uimod.read",
    "Uimod.write",
    "ctlmgr",
    "box.query",
    "box.set_config",
)

CALL_RE = re.compile(r"\b([A-Za-z_$][A-Za-z0-9_$.:]{1,127})\s*\(")
IDENT_RE = re.compile(r"[A-Za-z_$][A-Za-z0-9_$.:/-]{1,127}")
FUNCTION_RE = re.compile(
    r"(?:\bfunction\s+([A-Za-z_$][A-Za-z0-9_$.:]{1,127})|"
    r"([A-Za-z_$][A-Za-z0-9_$.:]{1,127})\s*=\s*function\b)"
)


def digest_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def digest_line(line: str) -> str:
    return hashlib.sha256(line.encode("utf-8", "replace")).hexdigest()


def enclosing_function(lines: list[str], index: int) -> str:
    for cursor in range(index, max(-1, index - 180), -1):
        match = FUNCTION_RE.search(lines[cursor])
        if match:
            return match.group(1) or match.group(2) or "<anonymous>"
    return "<top-level>"


def relevant_identifier(value: str) -> bool:
    low = value.lower()
    terms = (
        "ui", "uimod", "webvar", "module", "transaction", "ctlmgr", "box.",
        "query", "set", "get", "write", "read", "config", "request", "response",
        "api", "generic", "resource", "commit", "value",
    )
    return any(term in low for term in terms)


def write_tsv(path: pathlib.Path, header: tuple[str, ...], rows) -> None:
    with path.open("w", encoding="utf-8") as handle:
        handle.write("\t".join(header) + "\n")
        for row in rows:
            handle.write("\t".join(str(v).replace("\t", " ").replace("\n", " ") for v in row) + "\n")


def scan(root: pathlib.Path, output: pathlib.Path) -> None:
    output.mkdir(parents=True, exist_ok=True)
    files = []
    contexts = set()
    edges = set()
    functions = set()

    for relative in TARGETS:
        path = root / relative
        if not path.is_file():
            continue
        data = path.read_bytes()
        text = data.decode("utf-8", "replace")
        lines = text.splitlines()
        files.append((relative, len(data), digest_bytes(data), len(lines)))

        for index, line in enumerate(lines):
            fm = FUNCTION_RE.search(line)
            if fm:
                name = fm.group(1) or fm.group(2) or "<anonymous>"
                if relevant_identifier(name):
                    functions.add((relative, str(index + 1), name, digest_line(line)))

            matched = sorted(anchor for anchor in ANCHORS if anchor in line)
            if not matched:
                continue
            start = max(0, index - 10)
            stop = min(len(lines), index + 11)
            window = "\n".join(lines[start:stop])
            calls = sorted(set(CALL_RE.findall(window)))
            calls = [call for call in calls if relevant_identifier(call)]
            identifiers = sorted({token for token in IDENT_RE.findall(window) if relevant_identifier(token)})
            fn = enclosing_function(lines, index)
            line_hash = digest_line(line)
            contexts.add((
                relative,
                str(index + 1),
                line_hash,
                fn,
                ",".join(matched),
                ",".join(calls),
                ",".join(identifiers[:120]),
            ))
            for call in calls:
                edges.add((relative, fn, ",".join(matched), call, line_hash))

    write_tsv(output / "uimod-bridge-files.tsv", ("file", "bytes", "sha256", "lines"), sorted(files))
    write_tsv(output / "uimod-bridge-functions.tsv", ("file", "line", "function", "source_line_sha256"), sorted(functions))
    write_tsv(
        output / "uimod-bridge-context.tsv",
        ("file", "line", "source_line_sha256", "enclosing_function", "anchors", "nearby_calls", "semantic_identifiers"),
        sorted(contexts),
    )
    write_tsv(
        output / "uimod-bridge-edges.tsv",
        ("file", "enclosing_function", "anchors", "nearby_call", "source_line_sha256"),
        sorted(edges),
    )

    summary = {
        "schemaVersion": 1,
        "purpose": "dns-rest-api-uimod-bridge",
        "filesObserved": len(files),
        "functionRows": len(functions),
        "anchorContexts": len(contexts),
        "candidateEdges": len(edges),
        "hypothesis": "dns-api-config-convergence",
        "hypothesisStatus": "unresolved",
        "limitations": [
            "Nearby lexical calls are candidate control-flow evidence, not runtime execution proof.",
            "No source text, values, firmware payloads, or credentials are retained.",
            "Static evidence does not authorize mutation."
        ],
        "decisionRule": (
            "If Uimod exposes a bounded write/read path from api_generic to the same box/configuration "
            "boundary used by native cmtable, perform one exact-target corroboration pass; otherwise refute "
            "or revise the convergence hypothesis rather than broadening the search."
        ),
    }
    (output / "uimod-bridge-summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (output / "uimod-bridge-summary.md").write_text(
        "# REST generic API -> Uimod bridge\n\n"
        "Sanitized candidate evidence; convergence remains unresolved.\n\n"
        f"- filesObserved: {summary['filesObserved']}\n"
        f"- functionRows: {summary['functionRows']}\n"
        f"- anchorContexts: {summary['anchorContexts']}\n"
        f"- candidateEdges: {summary['candidateEdges']}\n",
        encoding="utf-8",
    )


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
