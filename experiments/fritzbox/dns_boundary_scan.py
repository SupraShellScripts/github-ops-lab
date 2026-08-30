#!/usr/bin/env python3
"""Emit sanitized DNS API/configuration-boundary evidence from exact FRITZ!OS.

This pass follows the convergence candidate scan. It intentionally examines only a
small, preselected set of text and ELF candidates. Output is structural metadata:
file hashes, line hashes/numbers, enclosing function names, call identifiers,
filtered dynamic symbol names, DT_NEEDED edges, and exact anchor offsets. It never
retains source lines, disassembly, firmware payloads, or configuration values.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
import re
import subprocess
from collections import defaultdict

TEXT_TARGETS = (
    "usr/rest_api/api_generic.lua",
    "usr/rest_api/security.lua",
    "etc/rest_api_resources.json",
    "usr/www/avm/js3/data/dnsserver.data.js",
    "usr/www/avm/js3/data/dnscfg.data.js",
    "usr/www/avm/internet/dnsserver.lua",
    "usr/lua/cmtable.lua",
    "usr/lua/internet.lua",
)

ELF_TARGETS = (
    "lib/libcmapi.so",
    "lib/libcm.so",
    "lib/libfbconf.so",
    "usr/bin/ctlmgr",
    "usr/share/ctlmgr/libconfigd.so",
)

ANCHORS = (
    "generic/dnsserver",
    "dnscfg:settings",
    "cmtable.add_var",
    "box.set_config",
    "dns_over_tls_enabled",
    "dns_over_tls_fqdns",
    "dns_over_tls_strict",
    "dns_over_tls_udp_fallback",
    "api_generic",
    "data-controller",
    "ctlmgr",
    "libcm",
    "libcmapi",
    "libfbconf",
    "libconfigd",
)

SEMANTIC_TERMS = (
    "api", "generic", "resource", "request", "response", "query", "get", "set",
    "config", "cm", "ctlmgr", "transaction", "txn", "value", "commit", "write",
    "read", "dns", "dot", "tls", "server",
)

CALL_RE = re.compile(r"\b([A-Za-z_$][A-Za-z0-9_$.:]{1,127})\s*\(")
IDENT_RE = re.compile(r"[A-Za-z_$][A-Za-z0-9_$.:/-]{1,127}")
FUNCTION_RE = re.compile(
    r"(?:\bfunction\s+([A-Za-z_$][A-Za-z0-9_$.:]{1,127})|"
    r"([A-Za-z_$][A-Za-z0-9_$.-]{1,127})\s*=\s*function\b)"
)
DYNAMIC_SYMBOL_RE = re.compile(
    r"^\s*\d+:\s+([0-9a-fA-F]+)\s+(\d+)\s+(\S+)\s+(\S+)\s+(\S+)\s+(\S+)\s+(.+?)\s*$"
)
NEEDED_RE = re.compile(r"\(NEEDED\).*?\[([^\]]+)\]")
MACHINE_RE = re.compile(r"^\s*Machine:\s*(.+?)\s*$", re.MULTILINE)


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8", "replace")).hexdigest()


def interesting(value: str) -> bool:
    low = value.lower()
    return any(term in low for term in SEMANTIC_TERMS)


def enclosing_function(lines: list[str], index: int) -> str:
    for cursor in range(index, max(-1, index - 160), -1):
        match = FUNCTION_RE.search(lines[cursor])
        if match:
            return match.group(1) or match.group(2) or "<anonymous>"
    return "<top-level>"


def run_text(args: list[str]) -> str:
    try:
        cp = subprocess.run(
            args,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            errors="replace",
            check=False,
            timeout=30,
        )
        return cp.stdout
    except (OSError, subprocess.TimeoutExpired):
        return ""


def write_tsv(path: pathlib.Path, header: tuple[str, ...], rows) -> None:
    with path.open("w", encoding="utf-8") as handle:
        handle.write("\t".join(header) + "\n")
        for row in rows:
            handle.write("\t".join(str(value).replace("\t", " ").replace("\n", " ") for value in row) + "\n")


def scan_text(root: pathlib.Path):
    file_rows = []
    context_rows = set()
    call_rows = set()

    for relative in TEXT_TARGETS:
        path = root / relative
        if not path.is_file():
            continue
        data = path.read_bytes()
        text = data.decode("utf-8", "replace")
        lines = text.splitlines()
        file_rows.append((relative, len(data), sha256_bytes(data), len(lines)))

        for index, line in enumerate(lines):
            matched = sorted(anchor for anchor in ANCHORS if anchor in line)
            if not matched:
                continue
            window = lines[max(0, index - 8): min(len(lines), index + 9)]
            window_text = "\n".join(window)
            calls = sorted({m.group(1) for m in CALL_RE.finditer(window_text) if interesting(m.group(1))})
            ids = sorted({value for value in IDENT_RE.findall(window_text) if interesting(value)})
            fn = enclosing_function(lines, index)
            line_hash = sha256_text(line)
            context_rows.add((
                relative,
                str(index + 1),
                line_hash,
                fn,
                ",".join(matched),
                ",".join(calls),
                ",".join(ids[:80]),
            ))
            for call in calls:
                call_rows.add((relative, fn, ",".join(matched), call, line_hash))

    return sorted(file_rows), sorted(context_rows), sorted(call_rows)


def scan_elf(root: pathlib.Path):
    file_rows = []
    dependency_rows = set()
    symbol_rows = set()
    offset_rows = set()

    for relative in ELF_TARGETS:
        path = root / relative
        if not path.is_file():
            continue
        data = path.read_bytes()
        digest = sha256_bytes(data)
        header = run_text(["readelf", "-hW", str(path)])
        dynamic = run_text(["readelf", "-dW", str(path)])
        symbols = run_text(["readelf", "-Ws", str(path)])
        machine_match = MACHINE_RE.search(header)
        machine = machine_match.group(1).strip() if machine_match else "unknown"
        file_rows.append((relative, len(data), digest, machine))

        for needed in sorted(set(NEEDED_RE.findall(dynamic))):
            dependency_rows.add((relative, needed))

        for line in symbols.splitlines():
            match = DYNAMIC_SYMBOL_RE.match(line)
            if not match:
                continue
            value, size, sym_type, bind, visibility, ndx, name = match.groups()
            name = name.strip().split("@", 1)[0]
            if not name or not interesting(name):
                continue
            symbol_rows.add((relative, name, sym_type, bind, visibility, ndx, value.lower(), size))

        for anchor in ANCHORS:
            needle = anchor.encode("ascii")
            start = 0
            while True:
                offset = data.find(needle, start)
                if offset < 0:
                    break
                offset_rows.add((relative, anchor, f"0x{offset:x}", digest))
                start = offset + 1

    return sorted(file_rows), sorted(dependency_rows), sorted(symbol_rows), sorted(offset_rows)


def scan(root: pathlib.Path, output: pathlib.Path) -> None:
    output.mkdir(parents=True, exist_ok=True)
    text_files, text_context, text_calls = scan_text(root)
    elf_files, deps, symbols, offsets = scan_elf(root)

    write_tsv(output / "boundary-text-files.tsv", ("file", "bytes", "sha256", "lines"), text_files)
    write_tsv(
        output / "boundary-text-context.tsv",
        ("file", "line", "source_line_sha256", "enclosing_function", "anchors", "nearby_calls", "semantic_identifiers"),
        text_context,
    )
    write_tsv(
        output / "boundary-text-calls.tsv",
        ("file", "enclosing_function", "anchors", "call", "source_line_sha256"),
        text_calls,
    )
    write_tsv(output / "boundary-elf-files.tsv", ("file", "bytes", "sha256", "machine"), elf_files)
    write_tsv(output / "boundary-elf-dependencies.tsv", ("file", "needed"), deps)
    write_tsv(
        output / "boundary-elf-symbols.tsv",
        ("file", "symbol", "type", "bind", "visibility", "ndx", "value", "size"),
        symbols,
    )
    write_tsv(output / "boundary-anchor-offsets.tsv", ("file", "anchor", "file_offset", "sha256"), offsets)

    symbols_by_file: dict[str, int] = defaultdict(int)
    for row in symbols:
        symbols_by_file[row[0]] += 1

    summary = {
        "schemaVersion": 1,
        "purpose": "dns-api-config-boundary-focused-evidence",
        "textFilesObserved": len(text_files),
        "textAnchorContexts": len(text_context),
        "textCallEdges": len(text_calls),
        "elfFilesObserved": len(elf_files),
        "elfDependencyEdges": len(deps),
        "filteredElfSymbols": len(symbols),
        "binaryAnchorOffsets": len(offsets),
        "filteredSymbolsByFile": dict(sorted(symbols_by_file.items())),
        "hypothesis": "dns-api-config-convergence",
        "hypothesisStatus": "unresolved",
        "limitations": [
            "Nearby text calls are bounded lexical context, not runtime call proof.",
            "Dynamic symbols and DT_NEEDED edges establish linkage vocabulary, not resource-specific execution flow.",
            "Binary anchor offsets establish exact-string presence only; they are not machine-code xrefs.",
            "No source lines, disassembly, binary payloads, credentials, or configuration values are retained.",
            "Static evidence does not authorize mutation."
        ],
        "nextGate": (
            "Promote only a minimal candidate edge that can be independently corroborated by exact-target "
            "call/xref evidence or live read-only behavior; otherwise keep the hypothesis unresolved."
        ),
    }
    (output / "boundary-summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    with (output / "boundary-summary.md").open("w", encoding="utf-8") as handle:
        handle.write("# DNS API/configuration boundary scan\n\n")
        handle.write("Sanitized focused evidence only; the convergence hypothesis remains unresolved.\n\n")
        for key in (
            "textFilesObserved", "textAnchorContexts", "textCallEdges", "elfFilesObserved",
            "elfDependencyEdges", "filteredElfSymbols", "binaryAnchorOffsets"
        ):
            handle.write(f"- {key}: {summary[key]}\n")
        handle.write("\nUse this result only to select the smallest next xref/call target.\n")


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
