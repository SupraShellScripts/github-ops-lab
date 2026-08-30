#!/usr/bin/env python3
"""Emit sanitized exact-firmware evidence for the FRITZ Web asset transformation boundary.

This focused flywheel pass is intentionally narrower than a general firmware RE scan. It
examines only native libraries implicated by exact-firmware dependency/symbol evidence in
Web serving, file replacement, localization, templating, and asset bundles. Output retains
only file metadata, DT_NEEDED edges, filtered dynamic symbols, provider/consumer relations,
and exact string offsets. It never retains binary payloads, disassembly, source text, or
router data.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
import re
import subprocess
from collections import defaultdict

ELF_TARGETS = (
    "lib/libcmapi.so",
    "usr/bin/ctlmgr",
    "lib/libwebsrv.so.2",
    "lib/libreplacement.so.0",
    "lib/liblocalize.so.0",
    "lib/libhtmltemplate.so.0",
    "lib/libasset_bundle.so.0",
)

FOCUS_SYMBOLS = (
    "websrv_set_file_replacement_init_func",
    "websrv_set_file_replacement_work_func",
    "websrv_set_file_replacement_exit_func",
    "websrv_set_language",
    "set_language_for_webserver",
    "Localize_SetTemporaryLanguage",
    "run_setlanguage",
    "init_webserver",
    "inform_webserver",
    "increase_signal_of_webserver",
    "webserver_set_luacgi_page",
    "webserver_set_luacgi_page_param",
)

ANCHORS = FOCUS_SYMBOLS + (
    "libwebsrv.so",
    "libreplacement.so",
    "liblocalize.so",
    "libhtmltemplate.so",
    "libasset_bundle.so",
    "usr/www",
    "/internet/",
    "dnsserver.js",
    "html2.js",
    "lang=",
    "javascript",
    "Content-Type",
)

SEMANTIC_TERMS = (
    "websrv", "webserver", "replacement", "localize", "language", "template", "asset",
    "bundle", "file", "path", "www", "http", "javascript", "content", "lua", "cgi",
)

DYNAMIC_SYMBOL_RE = re.compile(
    r"^\s*\d+:\s+([0-9a-fA-F]+)\s+(\d+)\s+(\S+)\s+(\S+)\s+(\S+)\s+(\S+)\s+(.+?)\s*$"
)
NEEDED_RE = re.compile(r"\(NEEDED\).*?\[([^\]]+)\]")
MACHINE_RE = re.compile(r"^\s*Machine:\s*(.+?)\s*$", re.MULTILINE)


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


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


def interesting_symbol(name: str) -> bool:
    low = name.lower()
    return any(term in low for term in SEMANTIC_TERMS) or name in FOCUS_SYMBOLS


def write_tsv(path: pathlib.Path, header: tuple[str, ...], rows) -> None:
    with path.open("w", encoding="utf-8") as handle:
        handle.write("\t".join(header) + "\n")
        for row in rows:
            handle.write("\t".join(str(value).replace("\t", " ").replace("\n", " ") for value in row) + "\n")


def scan(root: pathlib.Path, output: pathlib.Path) -> None:
    output.mkdir(parents=True, exist_ok=True)

    files = []
    dependencies = set()
    symbols = set()
    offsets = set()
    symbol_defs: dict[str, set[str]] = defaultdict(set)
    symbol_uses: dict[str, set[str]] = defaultdict(set)
    missing_targets = []

    for relative in ELF_TARGETS:
        path = root / relative
        if not path.is_file():
            missing_targets.append(relative)
            continue

        data = path.read_bytes()
        digest = sha256_bytes(data)
        header = run_text(["readelf", "-hW", str(path)])
        dynamic = run_text(["readelf", "-dW", str(path)])
        symbol_text = run_text(["readelf", "-Ws", str(path)])
        machine_match = MACHINE_RE.search(header)
        machine = machine_match.group(1).strip() if machine_match else "unknown"
        files.append((relative, len(data), digest, machine))

        for needed in sorted(set(NEEDED_RE.findall(dynamic))):
            if any(term in needed.lower() for term in ("web", "replace", "local", "template", "asset", "cmapi")):
                dependencies.add((relative, needed))

        for line in symbol_text.splitlines():
            match = DYNAMIC_SYMBOL_RE.match(line)
            if not match:
                continue
            value, size, sym_type, bind, visibility, ndx, name = match.groups()
            name = name.strip().split("@", 1)[0]
            if not name or not interesting_symbol(name):
                continue
            symbols.add((relative, name, sym_type, bind, visibility, ndx, value.lower(), size))
            if name in FOCUS_SYMBOLS:
                if ndx == "UND":
                    symbol_uses[name].add(relative)
                else:
                    symbol_defs[name].add(relative)

        for anchor in ANCHORS:
            needle = anchor.encode("ascii", "ignore")
            if not needle:
                continue
            start = 0
            while True:
                offset = data.find(needle, start)
                if offset < 0:
                    break
                offsets.add((relative, anchor, f"0x{offset:x}", digest))
                start = offset + 1

    relation_rows = []
    for symbol in FOCUS_SYMBOLS:
        providers = sorted(symbol_defs.get(symbol, set()))
        consumers = sorted(symbol_uses.get(symbol, set()))
        relation_rows.append((symbol, ",".join(providers), ",".join(consumers), len(providers), len(consumers)))

    write_tsv(output / "asset-transform-elf-files.tsv", ("file", "bytes", "sha256", "machine"), sorted(files))
    write_tsv(output / "asset-transform-dependencies.tsv", ("file", "needed"), sorted(dependencies))
    write_tsv(
        output / "asset-transform-symbols.tsv",
        ("file", "symbol", "type", "bind", "visibility", "ndx", "value", "size"),
        sorted(symbols),
    )
    write_tsv(
        output / "asset-transform-symbol-relations.tsv",
        ("symbol", "providers", "consumers", "provider_count", "consumer_count"),
        relation_rows,
    )
    write_tsv(
        output / "asset-transform-anchor-offsets.tsv",
        ("file", "anchor", "file_offset", "sha256"),
        sorted(offsets),
    )

    provider_resolved = sum(1 for row in relation_rows if row[3] > 0)
    consumer_resolved = sum(1 for row in relation_rows if row[4] > 0)
    summary = {
        "schemaVersion": 1,
        "purpose": "exact-firmware-web-asset-transformation-focused-evidence",
        "targetCount": len(ELF_TARGETS),
        "targetsObserved": len(files),
        "missingTargets": missing_targets,
        "dependencyEdges": len(dependencies),
        "filteredSymbols": len(symbols),
        "anchorOffsets": len(offsets),
        "focusSymbols": len(FOCUS_SYMBOLS),
        "focusSymbolsWithProvider": provider_resolved,
        "focusSymbolsWithConsumer": consumer_resolved,
        "hypothesis": "firmware-file-to-served-web-asset-transformation-boundary",
        "hypothesisStatus": "focused-static-evidence-only",
        "limitations": [
            "Dynamic symbol provider/consumer relations establish linkage direction, not runtime call execution.",
            "Exact anchor offsets establish string presence only; they are not machine-code xrefs.",
            "No binary payloads, disassembly, source text, router configuration, or credentials are retained.",
            "This pass cannot prove which transformation caused any particular live served-asset difference.",
            "Static evidence does not authorize mutation."
        ],
        "nextGate": (
            "If one or two provider/consumer edges explain the active representation blocker, target only those "
            "functions for xref/decompilation; otherwise stop rather than widening to unrelated firmware."
        ),
    }
    (output / "asset-transform-summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    with (output / "asset-transform-summary.md").open("w", encoding="utf-8") as handle:
        handle.write("# FRITZ Web asset transformation boundary scan\n\n")
        handle.write("Sanitized exact-firmware evidence for the focused live/static flywheel question.\n\n")
        for key in (
            "targetsObserved", "dependencyEdges", "filteredSymbols", "anchorOffsets",
            "focusSymbolsWithProvider", "focusSymbolsWithConsumer"
        ):
            handle.write(f"- {key}: {summary[key]}\n")
        if missing_targets:
            handle.write(f"- missingTargets: {', '.join(missing_targets)}\n")
        handle.write("\nUse only to select the smallest next native xref/decompilation target.\n")


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
