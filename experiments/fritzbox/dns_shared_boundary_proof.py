#!/usr/bin/env python3
"""Corroborate the smallest shared DNS configuration boundary.

This final MVP static pass does not attempt broad reverse engineering. It records
only structural facts needed to decide whether the native DNS page and generic
REST API reach the same `box.set_config` boundary. Output never contains source
text, configuration values, disassembly, or firmware payloads.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
import re

FILES = (
    "usr/www/avm/internet/dnsserver.lua",
    "usr/lua/cmtable.lua",
    "usr/lua/uimod.lua",
    "usr/rest_api/api_generic.lua",
    "usr/rest_api/uimod.lua",
)

FACT_PATTERNS = {
    "native-dns-add-var": re.compile(r"cmtable\s*\.\s*add_var\s*\("),
    "native-cmtable-commit": re.compile(r"cmtable\s*\.\s*commit\s*\("),
    "shared-box-set-config": re.compile(r"box\s*\.\s*set_config\s*\("),
    "shared-box-query": re.compile(r"box\s*\.\s*(?:recursive_query|query)\s*\("),
    "rest-uimod-new": re.compile(r"Uimod\s*[:.]\s*new\s*\("),
    "rest-ui-set-webvar": re.compile(r"ui\s*:\s*set_webvar\s*\("),
    "rest-ui-get-module": re.compile(r"ui\s*:\s*get_module\s*\("),
    "rest-ui-transaction": re.compile(r"ui\s*\.\s*transaction\b"),
}

FUNCTION_RE = re.compile(
    r"(?:\bfunction\s+([A-Za-z_$][A-Za-z0-9_$.:]{1,127})|"
    r"([A-Za-z_$][A-Za-z0-9_$.:]{1,127})\s*=\s*function\b)"
)
UIMOD_BIND_RE = re.compile(r"\b(?:local\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=\s*Uimod\s*[:.]\s*new\s*\(")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_line(line: str) -> str:
    return hashlib.sha256(line.encode("utf-8", "replace")).hexdigest()


def enclosing_function(lines: list[str], index: int) -> str:
    for cursor in range(index, max(-1, index - 180), -1):
        match = FUNCTION_RE.search(lines[cursor])
        if match:
            return match.group(1) or match.group(2) or "<anonymous>"
    return "<top-level>"


def write_tsv(path: pathlib.Path, header: tuple[str, ...], rows) -> None:
    with path.open("w", encoding="utf-8") as handle:
        handle.write("\t".join(header) + "\n")
        for row in rows:
            handle.write("\t".join(str(v).replace("\t", " ").replace("\n", " ") for v in row) + "\n")


def scan_all_cmtable_commit_refs(root: pathlib.Path):
    rows = []
    for path in sorted(root.rglob("*.lua")):
        try:
            data = path.read_bytes()
        except OSError:
            continue
        if b"cmtable.commit" not in data:
            continue
        text = data.decode("utf-8", "replace")
        lines = text.splitlines()
        relative = path.relative_to(root).as_posix()
        digest = sha256_bytes(data)
        for index, line in enumerate(lines):
            if "cmtable.commit" not in line:
                continue
            rows.append((relative, str(index + 1), enclosing_function(lines, index), sha256_line(line), digest))
    return rows


def scan(root: pathlib.Path, output: pathlib.Path) -> None:
    output.mkdir(parents=True, exist_ok=True)
    files = []
    facts = []
    bindings = []

    for relative in FILES:
        path = root / relative
        if not path.is_file():
            continue
        data = path.read_bytes()
        digest = sha256_bytes(data)
        text = data.decode("utf-8", "replace")
        lines = text.splitlines()
        files.append((relative, len(data), digest, len(lines)))
        for index, line in enumerate(lines):
            line_hash = sha256_line(line)
            fn = enclosing_function(lines, index)
            for fact, pattern in FACT_PATTERNS.items():
                if pattern.search(line):
                    facts.append((fact, relative, str(index + 1), fn, line_hash, digest))
            bind = UIMOD_BIND_RE.search(line)
            if bind:
                bindings.append((relative, str(index + 1), bind.group(1), "Uimod:new", line_hash, digest))

    commit_refs = scan_all_cmtable_commit_refs(root)

    write_tsv(output / "shared-boundary-files.tsv", ("file", "bytes", "sha256", "lines"), sorted(files))
    write_tsv(
        output / "shared-boundary-facts.tsv",
        ("fact", "file", "line", "enclosing_function", "source_line_sha256", "file_sha256"),
        sorted(facts),
    )
    write_tsv(
        output / "uimod-bindings.tsv",
        ("file", "line", "variable", "constructor", "source_line_sha256", "file_sha256"),
        sorted(bindings),
    )
    write_tsv(
        output / "cmtable-commit-callers.tsv",
        ("file", "line", "enclosing_function", "source_line_sha256", "file_sha256"),
        sorted(commit_refs),
    )

    fact_names = {row[0] for row in facts}
    api_ui_bound = any(row[2] == "ui" for row in bindings if row[0] == "usr/rest_api/api_generic.lua")
    rest_to_box = (
        "rest-ui-set-webvar" in fact_names
        and "shared-box-set-config" in fact_names
        and api_ui_bound
    )
    native_adds = "native-dns-add-var" in fact_names
    native_commit_exists = any(row[0] != "usr/lua/cmtable.lua" for row in commit_refs)
    cmtable_to_box = any(
        row[0] == "shared-box-set-config" and row[1] == "usr/lua/cmtable.lua"
        for row in facts
    )

    summary = {
        "schemaVersion": 1,
        "purpose": "dns-shared-box-set-config-boundary-corroboration",
        "apiGenericUiBoundToUimod": api_ui_bound,
        "restSetWebvarPathObserved": "rest-ui-set-webvar" in fact_names,
        "restUimodBoxSetConfigObserved": any(
            row[0] == "shared-box-set-config" and row[1] == "usr/rest_api/uimod.lua"
            for row in facts
        ),
        "nativeDnsCmtableAddVarObserved": native_adds,
        "nativeCmtableCommitCallerObservedOutsideCmtableModule": native_commit_exists,
        "cmtableBoxSetConfigObserved": cmtable_to_box,
        "restStructuralBridgeToSharedBoundary": rest_to_box,
        "hypothesisDecision": "unresolved",
        "limitations": [
            "Function association is structural/source-level evidence and not runtime tracing.",
            "A shared box.set_config boundary does not by itself prove identical downstream libcm transaction semantics.",
            "No source lines, values, payloads, disassembly, credentials, or live mutation are retained."
        ],
    }
    if (
        api_ui_bound
        and summary["restSetWebvarPathObserved"]
        and summary["restUimodBoxSetConfigObserved"]
        and native_adds
        and native_commit_exists
        and cmtable_to_box
    ):
        summary["hypothesisDecision"] = "shared-box-set-config-boundary-supported"

    (output / "shared-boundary-summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (output / "shared-boundary-summary.md").write_text(
        "# DNS shared configuration boundary corroboration\n\n"
        f"- decision: {summary['hypothesisDecision']}\n"
        f"- apiGenericUiBoundToUimod: {str(api_ui_bound).lower()}\n"
        f"- restUimodBoxSetConfigObserved: {str(summary['restUimodBoxSetConfigObserved']).lower()}\n"
        f"- nativeDnsCmtableAddVarObserved: {str(native_adds).lower()}\n"
        f"- nativeCmtableCommitCallerObservedOutsideCmtableModule: {str(native_commit_exists).lower()}\n"
        f"- cmtableBoxSetConfigObserved: {str(cmtable_to_box).lower()}\n\n"
        "This supports only the shared box.set_config boundary; deeper libcm transaction equivalence remains a separate question.\n",
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
