#!/usr/bin/env python3
"""Emit sanitized xref/callsite evidence for the FRITZ Web replacement callback seam.

This is a probe-informed flywheel pass, not a general decompiler. It examines only the
exact-firmware Web replacement registration/processing neighborhood selected by the prior
provider/consumer scan. Raw disassembly is used ephemerally and never written to output.
Published evidence is limited to binary hashes, function ranges, referenced symbol names,
callsite offsets, containing exported-function ranges where provable, nearest exported
symbol hints where ownership is unresolved, and decision-oriented summary assertions.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
import re
import subprocess
from collections import defaultdict

TARGETS = (
    "lib/libcmapi.so",
    "lib/libreplacement.so.0",
    "lib/libwebsrv.so.2",
)

CMAPI = "lib/libcmapi.so"
REPLACEMENT = "lib/libreplacement.so.0"
WEBSRV = "lib/libwebsrv.so.2"

SETTER_SYMBOLS = (
    "websrv_set_file_replacement_init_func",
    "websrv_set_file_replacement_work_func",
    "websrv_set_file_replacement_exit_func",
)

PROCESSING_SYMBOLS = (
    "replacement_init_context",
    "replacement_processing",
    "replacement_processing_ex",
    "replacement_processing_end",
)

TARGET_FUNCTIONS = (
    "init_webserver",
    "set_language_for_webserver",
    "replacement_init_context",
    "replacement_processing",
    "replacement_processing_ex",
    "replacement_processing_end",
)

FOCUS_REFERENCES = SETTER_SYMBOLS + PROCESSING_SYMBOLS

DYNAMIC_SYMBOL_RE = re.compile(
    r"^\s*\d+:\s+([0-9a-fA-F]+)\s+(\d+)\s+(\S+)\s+(\S+)\s+(\S+)\s+(\S+)\s+(.+?)\s*$"
)
INSTRUCTION_RE = re.compile(r"^\s*([0-9a-fA-F]+):\s")
LABEL_RE = re.compile(r"^\s*([0-9a-fA-F]+)\s+<([^>]+)>:\s*$")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def run_text(args: list[str], timeout: int = 60) -> str:
    try:
        cp = subprocess.run(
            args,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            errors="replace",
            check=False,
            timeout=timeout,
        )
        return cp.stdout
    except (OSError, subprocess.TimeoutExpired):
        return ""


def write_tsv(path: pathlib.Path, header: tuple[str, ...], rows) -> None:
    with path.open("w", encoding="utf-8") as handle:
        handle.write("\t".join(header) + "\n")
        for row in rows:
            handle.write("\t".join(str(v).replace("\t", " ").replace("\n", " ") for v in row) + "\n")


def normalized_symbol(name: str) -> str:
    name = name.strip().split("@", 1)[0]
    if name.endswith("@plt"):
        name = name[:-4]
    return name


def parse_functions(symbol_text: str) -> list[dict]:
    rows = []
    seen = set()
    for line in symbol_text.splitlines():
        match = DYNAMIC_SYMBOL_RE.match(line)
        if not match:
            continue
        value, size, sym_type, bind, visibility, ndx, name = match.groups()
        name = normalized_symbol(name)
        if sym_type != "FUNC" or ndx == "UND" or not name:
            continue
        try:
            start = int(value, 16)
            length = int(size)
        except ValueError:
            continue
        if start <= 0 or length <= 0:
            continue
        key = (start, length, name)
        if key in seen:
            continue
        seen.add(key)
        rows.append({
            "name": name,
            "start": start,
            "size": length,
            "end": start + length,
            "bind": bind,
            "visibility": visibility,
        })
    return sorted(rows, key=lambda r: (r["start"], r["size"], r["name"]))


def find_owner(functions: list[dict], address: int) -> dict | None:
    candidates = [f for f in functions if f["start"] <= address < f["end"]]
    if not candidates:
        return None
    # Smallest containing exported range is the least over-broad provable owner.
    return sorted(candidates, key=lambda f: (f["size"], -f["start"], f["name"]))[0]


def nearest_preceding(functions: list[dict], address: int) -> tuple[dict | None, int | None]:
    candidates = [f for f in functions if f["start"] <= address]
    if not candidates:
        return None, None
    nearest = max(candidates, key=lambda f: f["start"])
    return nearest, address - nearest["start"]


def reference_symbol_from_line(line: str) -> str | None:
    for symbol in FOCUS_REFERENCES:
        if re.search(rf"(?<![A-Za-z0-9_]){re.escape(symbol)}(?:@[^\s+]+)?(?![A-Za-z0-9_])", line):
            return symbol
    return None


def parse_focus_references(disassembly: str, functions: list[dict]) -> list[dict]:
    refs = []
    last_instruction_address: int | None = None
    last_label: str | None = None
    for line in disassembly.splitlines():
        label_match = LABEL_RE.match(line)
        if label_match:
            last_label = normalized_symbol(label_match.group(2))
            continue
        insn_match = INSTRUCTION_RE.match(line)
        if insn_match:
            last_instruction_address = int(insn_match.group(1), 16)
        symbol = reference_symbol_from_line(line)
        if not symbol or last_instruction_address is None:
            continue
        address = last_instruction_address
        owner = find_owner(functions, address)
        nearest, distance = nearest_preceding(functions, address)
        refs.append({
            "symbol": symbol,
            "callsite": address,
            "owner": owner["name"] if owner else "<unresolved>",
            "ownerStart": owner["start"] if owner else None,
            "ownerSize": owner["size"] if owner else None,
            "nearestExported": nearest["name"] if nearest else "<none>",
            "nearestExportedStart": nearest["start"] if nearest else None,
            "distanceFromNearestExported": distance,
            "objdumpLabel": last_label or "<none>",
        })
    # objdump may surface both instruction and relocation annotations for one reference.
    dedup = {}
    for ref in refs:
        dedup[(ref["symbol"], ref["callsite"])] = ref
    return sorted(dedup.values(), key=lambda r: (r["callsite"], r["symbol"]))


def format_hex(value: int | None) -> str:
    return "" if value is None else f"0x{value:x}"


def scan(root: pathlib.Path, output: pathlib.Path) -> None:
    output.mkdir(parents=True, exist_ok=True)
    file_rows = []
    function_rows = []
    xref_rows = []
    all_refs: dict[str, list[dict]] = {}
    functions_by_file: dict[str, list[dict]] = {}
    missing = []

    for relative in TARGETS:
        path = root / relative
        if not path.is_file():
            missing.append(relative)
            continue
        data = path.read_bytes()
        digest = sha256_bytes(data)
        symbol_text = run_text(["readelf", "-Ws", str(path)])
        functions = parse_functions(symbol_text)
        functions_by_file[relative] = functions
        disassembly = run_text(["objdump", "-drwC", str(path)], timeout=120)
        refs = parse_focus_references(disassembly, functions)
        all_refs[relative] = refs
        file_rows.append((relative, len(data), digest, len(functions), len(refs)))

        target_names = set(TARGET_FUNCTIONS)
        for fn in functions:
            if fn["name"] in target_names:
                function_rows.append((
                    relative,
                    fn["name"],
                    format_hex(fn["start"]),
                    fn["size"],
                    format_hex(fn["end"]),
                    fn["bind"],
                    fn["visibility"],
                ))

        for ref in refs:
            xref_rows.append((
                relative,
                ref["symbol"],
                format_hex(ref["callsite"]),
                ref["owner"],
                format_hex(ref["ownerStart"]),
                ref["ownerSize"] if ref["ownerSize"] is not None else "",
                ref["nearestExported"],
                format_hex(ref["nearestExportedStart"]),
                ref["distanceFromNearestExported"] if ref["distanceFromNearestExported"] is not None else "",
            ))

    cmapi_refs = all_refs.get(CMAPI, [])
    setter_refs = [r for r in cmapi_refs if r["symbol"] in SETTER_SYMBOLS]
    processing_refs = [r for r in cmapi_refs if r["symbol"] in PROCESSING_SYMBOLS]

    setter_by_symbol: dict[str, list[dict]] = defaultdict(list)
    for ref in setter_refs:
        setter_by_symbol[ref["symbol"]].append(ref)

    all_setters_observed = all(len(setter_by_symbol[s]) > 0 for s in SETTER_SYMBOLS)
    all_setters_owned_by_init = all(
        len(setter_by_symbol[s]) > 0 and all(r["owner"] == "init_webserver" for r in setter_by_symbol[s])
        for s in SETTER_SYMBOLS
    )
    registration_sequence = [
        {"symbol": r["symbol"], "callsite": format_hex(r["callsite"]), "owner": r["owner"]}
        for r in sorted(setter_refs, key=lambda r: r["callsite"])
    ]

    processing_consumers: dict[str, dict] = {}
    for symbol in PROCESSING_SYMBOLS:
        refs = [r for r in processing_refs if r["symbol"] == symbol]
        processing_consumers[symbol] = {
            "callsiteCount": len(refs),
            "provableOwners": sorted({r["owner"] for r in refs if r["owner"] != "<unresolved>"}),
            "unresolvedCallsites": [format_hex(r["callsite"]) for r in refs if r["owner"] == "<unresolved>"],
            "nearestExportedHints": sorted({
                (r["nearestExported"], r["distanceFromNearestExported"])
                for r in refs if r["owner"] == "<unresolved>" and r["nearestExported"] != "<none>"
            }),
        }
        processing_consumers[symbol]["nearestExportedHints"] = [
            {"symbol": name, "distanceBytes": distance} for name, distance in processing_consumers[symbol]["nearestExportedHints"]
        ]

    replacement_functions = functions_by_file.get(REPLACEMENT, [])
    replacement_definitions = {
        name: [
            {"start": format_hex(f["start"]), "size": f["size"]}
            for f in replacement_functions if f["name"] == name
        ]
        for name in PROCESSING_SYMBOLS
    }

    write_tsv(
        output / "callback-xref-elf-files.tsv",
        ("file", "bytes", "sha256", "defined_function_ranges", "focus_reference_sites"),
        sorted(file_rows),
    )
    write_tsv(
        output / "callback-xref-target-functions.tsv",
        ("file", "function", "start", "size", "end", "bind", "visibility"),
        sorted(function_rows),
    )
    write_tsv(
        output / "callback-xref-sites.tsv",
        (
            "file", "referenced_symbol", "callsite", "provable_owner", "owner_start", "owner_size",
            "nearest_exported_symbol", "nearest_exported_start", "distance_from_nearest_exported"
        ),
        sorted(xref_rows),
    )

    summary = {
        "schemaVersion": 1,
        "purpose": "probe-informed-web-replacement-callback-xref-evidence",
        "targetsRequested": list(TARGETS),
        "targetsObserved": len(file_rows),
        "missingTargets": missing,
        "hypotheses": {
            "h1CallbackRegistration": {
                "allThreeSetterReferencesObservedInLibcmapi": all_setters_observed,
                "allThreeSetterReferencesProvablyInsideInitWebserver": all_setters_owned_by_init,
                "registrationSequence": registration_sequence,
            },
            "h2ReplacementProcessingConsumers": processing_consumers,
            "replacementProviderDefinitions": replacement_definitions,
        },
        "decision": {
            "registrationOwnerNarrowed": all_setters_owned_by_init,
            "processingConsumerRegionsObserved": sum(v["callsiteCount"] for v in processing_consumers.values()),
            "nextDecompilationEligible": bool(all_setters_owned_by_init and sum(v["callsiteCount"] for v in processing_consumers.values()) > 0),
        },
        "limitations": [
            "Symbol/callsite evidence does not prove runtime execution on a specific HTTP request.",
            "Containing exported-function ownership is asserted only when the callsite lies inside a defined nonzero symbol range.",
            "Nearest exported symbols for unresolved callsites are location hints, not ownership claims.",
            "Raw disassembly and binary payloads are not retained.",
            "This pass cannot by itself prove that file replacement caused the observed dnsserver.js byte difference.",
            "Static evidence does not authorize router mutation."
        ],
        "nextGate": (
            "If replacement callback registration and processing consumers are reduced to one or two bounded code regions, "
            "decompile only those regions if their semantics can change the active DNS form-encoding decision; otherwise stop."
        ),
    }
    (output / "callback-xref-summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    with (output / "callback-xref-summary.md").open("w", encoding="utf-8") as handle:
        handle.write("# FRITZ Web replacement callback xref scan\n\n")
        handle.write("Probe-informed, exact-firmware, sanitized static evidence.\n\n")
        handle.write(f"- targetsObserved: {summary['targetsObserved']}\n")
        handle.write(f"- allThreeSetterReferencesObservedInLibcmapi: {str(all_setters_observed).lower()}\n")
        handle.write(f"- allThreeSetterReferencesProvablyInsideInitWebserver: {str(all_setters_owned_by_init).lower()}\n")
        handle.write(f"- processingConsumerReferenceSites: {summary['decision']['processingConsumerRegionsObserved']}\n")
        handle.write(f"- nextDecompilationEligible: {str(summary['decision']['nextDecompilationEligible']).lower()}\n")
        if missing:
            handle.write(f"- missingTargets: {', '.join(missing)}\n")
        handle.write("\nNo raw disassembly or firmware payload is retained.\n")


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
