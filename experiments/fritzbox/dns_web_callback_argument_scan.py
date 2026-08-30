#!/usr/bin/env python3
"""Recover sanitized callback arguments for FRITZ Web file-replacement registration.

This is a narrow child of the proven MIPS GOT-mediated call recovery. It resolves only the
first argument supplied to the three websrv_set_file_replacement_* setter calls inside
libcmapi.so::init_webserver, then checks a small callback window for the corresponding
replacement lifecycle import. Raw disassembly and proprietary firmware payloads are never
retained.
"""
from __future__ import annotations

import argparse
import json
import pathlib
import re

from dns_web_mips_got_xref_scan import (
    CMAPI,
    SETTER_SYMBOLS,
    PROCESSING_SYMBOLS,
    format_hex,
    parse_functions,
    parse_instructions,
    parse_mips_got,
    recover_calls,
    run_text,
    select_mips_objdump,
    write_tsv,
)

ALL_GOT_LINE_RE = re.compile(
    r"^\s*([0-9a-fA-F]+)\s+(-?\d+)\(gp\)\s+([0-9a-fA-F]+)(?:\s+.*)?$"
)
LW_REG_GP_RE = re.compile(
    r"\b(?:lw|ld)\s+(a0|\$4|[atsv][0-9]|\$\d+),\s*(-?\d+)\((?:gp|\$28)\)", re.IGNORECASE
)
MOVE_RE = re.compile(
    r"\bmove\s+(a0|\$4|[atsv][0-9]|\$\d+),\s*(a0|\$4|[atsv][0-9]|\$\d+)\b", re.IGNORECASE
)
ADDIU_GP_RE = re.compile(
    r"\baddiu\s+(a0|\$4|[atsv][0-9]|\$\d+),\s*(?:gp|\$28),\s*(-?\d+)\b", re.IGNORECASE
)
LI_RE = re.compile(
    r"\bli\s+(a0|\$4|[atsv][0-9]|\$\d+),\s*(0x[0-9a-fA-F]+|-?\d+)\b", re.IGNORECASE
)
GENERIC_REG_WRITE_RE = re.compile(
    r"\b(?:lw|ld|la|li|move|addu|addiu|ori|lui|sll|srl)\s+([a-z][a-z0-9]*|\$\d+)\b", re.IGNORECASE
)

ROLE_EXPECTED_IMPORT = {
    "websrv_set_file_replacement_init_func": "replacement_init_context",
    "websrv_set_file_replacement_work_func": "replacement_processing",
    "websrv_set_file_replacement_exit_func": "replacement_processing_end",
}


def normalize_reg(reg: str) -> str:
    reg = reg.lower()
    aliases = {"$4": "a0", "$25": "t9", "$28": "gp"}
    return aliases.get(reg, reg)


def parse_all_got_entries(readelf_all: str) -> dict[int, dict]:
    entries: dict[int, dict] = {}
    for line in readelf_all.splitlines():
        m = ALL_GOT_LINE_RE.match(line)
        if not m:
            continue
        address, access, initial = m.groups()
        try:
            offset = int(access)
            got_address = int(address, 16)
            initial_value = int(initial, 16)
        except ValueError:
            continue
        entries[offset] = {
            "gpOffset": offset,
            "gotAddress": got_address,
            "initialValue": initial_value,
        }
    return entries


def instruction_index_by_address(instructions: list[dict]) -> dict[int, int]:
    return {row["address"]: index for index, row in enumerate(instructions)}


def resolve_register_source(
    instructions: list[dict],
    call_index: int,
    all_got: dict[int, dict],
    canonical_gp: int | None,
    start_reg: str = "a0",
    max_back: int = 20,
) -> dict:
    tracked = normalize_reg(start_reg)
    for index in range(call_index - 1, max(-1, call_index - max_back - 1), -1):
        asm = instructions[index]["asm"]

        move_match = MOVE_RE.search(asm)
        if move_match and normalize_reg(move_match.group(1)) == tracked:
            tracked = normalize_reg(move_match.group(2))
            continue

        lw_match = LW_REG_GP_RE.search(asm)
        if lw_match and normalize_reg(lw_match.group(1)) == tracked:
            offset = int(lw_match.group(2))
            got = all_got.get(offset)
            return {
                "resolved": got is not None,
                "kind": "gp-got-load",
                "sourceInstruction": instructions[index]["address"],
                "trackedRegister": tracked,
                "gpOffset": offset,
                "gotAddress": got["gotAddress"] if got else None,
                "value": got["initialValue"] if got else None,
                "reason": None if got else "gp-offset-not-found-in-primary-got",
            }

        addiu_match = ADDIU_GP_RE.search(asm)
        if addiu_match and normalize_reg(addiu_match.group(1)) == tracked:
            immediate = int(addiu_match.group(2))
            return {
                "resolved": canonical_gp is not None,
                "kind": "gp-relative-address",
                "sourceInstruction": instructions[index]["address"],
                "trackedRegister": tracked,
                "gpOffset": immediate,
                "gotAddress": None,
                "value": canonical_gp + immediate if canonical_gp is not None else None,
                "reason": None if canonical_gp is not None else "canonical-gp-unavailable",
            }

        li_match = LI_RE.search(asm)
        if li_match and normalize_reg(li_match.group(1)) == tracked:
            literal = int(li_match.group(2), 0)
            return {
                "resolved": True,
                "kind": "literal",
                "sourceInstruction": instructions[index]["address"],
                "trackedRegister": tracked,
                "gpOffset": None,
                "gotAddress": None,
                "value": literal,
                "reason": None,
            }

        write_match = GENERIC_REG_WRITE_RE.search(asm)
        if write_match and normalize_reg(write_match.group(1)) == tracked:
            return {
                "resolved": False,
                "kind": "unsupported-write-form",
                "sourceInstruction": instructions[index]["address"],
                "trackedRegister": tracked,
                "gpOffset": None,
                "gotAddress": None,
                "value": None,
                "reason": "tracked-register-written-by-unsupported-instruction-form",
            }

    return {
        "resolved": False,
        "kind": "not-found",
        "sourceInstruction": None,
        "trackedRegister": tracked,
        "gpOffset": None,
        "gotAddress": None,
        "value": None,
        "reason": "no-a0-source-found-in-bounded-window",
    }


def exact_symbol_at(functions: list[dict], address: int | None) -> str | None:
    if address is None:
        return None
    matches = sorted({fn["name"] for fn in functions if fn["start"] == address})
    if len(matches) == 1:
        return matches[0]
    return None


def focus_calls_in_window(all_calls: list[dict], start: int | None, size: int = 0x300) -> list[dict]:
    if start is None:
        return []
    stop = start + size
    return [call for call in all_calls if start <= call["callsite"] < stop]


def scan(root: pathlib.Path, output: pathlib.Path) -> None:
    output.mkdir(parents=True, exist_ok=True)
    path = root / CMAPI
    if not path.is_file():
        raise RuntimeError(f"required target missing: {CMAPI}")

    header = run_text(["readelf", "-hW", str(path)])
    symbols = run_text(["readelf", "-Ws", str(path)])
    readelf_all = run_text(["readelf", "-aW", str(path)])
    objdump = select_mips_objdump(header)
    disassembly = run_text([objdump, "-dw", str(path)])

    functions = parse_functions(symbols)
    canonical_gp, focus_got = parse_mips_got(readelf_all)
    all_got = parse_all_got_entries(readelf_all)
    instructions = parse_instructions(disassembly)
    if len(instructions) < 100:
        raise RuntimeError(f"MIPS cross-disassembly produced too few instructions: {len(instructions)}")

    all_focus_calls = recover_calls(instructions, focus_got, functions)
    setter_calls = [
        call for call in all_focus_calls
        if call["symbol"] in SETTER_SYMBOLS and call["owner"] == "init_webserver"
    ]
    calls_by_symbol = {symbol: [c for c in setter_calls if c["symbol"] == symbol] for symbol in SETTER_SYMBOLS}
    if not all(len(calls_by_symbol[symbol]) == 1 for symbol in SETTER_SYMBOLS):
        counts = {symbol: len(calls_by_symbol[symbol]) for symbol in SETTER_SYMBOLS}
        raise RuntimeError(f"expected exactly one in-init_webserver call for each setter: {counts}")

    index_by_address = instruction_index_by_address(instructions)
    result_rows = []
    results = []

    for setter in SETTER_SYMBOLS:
        call = calls_by_symbol[setter][0]
        call_index = index_by_address.get(call["callsite"])
        if call_index is None:
            raise RuntimeError(f"callsite missing from decoded instruction index: {setter}")
        arg = resolve_register_source(instructions, call_index, all_got, canonical_gp, start_reg="a0")
        target = arg["value"] if arg["resolved"] else None
        target_symbol = exact_symbol_at(functions, target)
        nearby = focus_calls_in_window(all_focus_calls, target)
        nearby_processing = [c for c in nearby if c["symbol"] in PROCESSING_SYMBOLS]
        expected_import = ROLE_EXPECTED_IMPORT[setter]
        expected_seen = any(c["symbol"] == expected_import for c in nearby_processing)

        result = {
            "setter": setter,
            "setterCallsite": call["callsite"],
            "argument": arg,
            "callbackTarget": target,
            "callbackExactExportedSymbol": target_symbol,
            "inspectionWindowBytes": 0x300,
            "focusCallsInWindow": [
                {
                    "symbol": c["symbol"],
                    "callsite": c["callsite"],
                    "owner": c["owner"],
                }
                for c in nearby_processing
            ],
            "expectedLifecycleImport": expected_import,
            "expectedLifecycleImportObserved": expected_seen,
        }
        results.append(result)
        result_rows.append((
            setter,
            format_hex(call["callsite"]),
            arg["kind"],
            format_hex(arg["sourceInstruction"]),
            "" if arg["gpOffset"] is None else arg["gpOffset"],
            format_hex(arg["gotAddress"]),
            format_hex(target),
            target_symbol or "<anonymous-or-unexported>",
            expected_import,
            str(expected_seen).lower(),
            ",".join(f"{c['symbol']}@{format_hex(c['callsite'])}" for c in nearby_processing),
        ))

    all_arguments_resolved = all(item["argument"]["resolved"] for item in results)
    lifecycle_mapping_supported = all(item["expectedLifecycleImportObserved"] for item in results)
    callback_targets = [item["callbackTarget"] for item in results if item["callbackTarget"] is not None]
    unique_callback_targets = len(callback_targets) == 3 and len(set(callback_targets)) == 3

    write_tsv(
        output / "callback-registration-arguments.tsv",
        (
            "setter", "setter_callsite", "a0_source_kind", "a0_source_instruction", "a0_gp_offset",
            "a0_got_address", "callback_target", "callback_exact_exported_symbol",
            "expected_lifecycle_import", "expected_lifecycle_import_observed", "focus_calls_in_callback_window"
        ),
        result_rows,
    )

    summary = {
        "schemaVersion": 1,
        "purpose": "probe-informed-web-file-replacement-callback-argument-recovery",
        "target": CMAPI,
        "decodedInstructions": len(instructions),
        "disassembler": pathlib.Path(objdump).name,
        "canonicalGp": format_hex(canonical_gp),
        "setterCalls": [
            {
                "setter": item["setter"],
                "setterCallsite": format_hex(item["setterCallsite"]),
                "argument": {
                    "resolved": item["argument"]["resolved"],
                    "kind": item["argument"]["kind"],
                    "sourceInstruction": format_hex(item["argument"]["sourceInstruction"]),
                    "gpOffset": item["argument"]["gpOffset"],
                    "gotAddress": format_hex(item["argument"]["gotAddress"]),
                    "callbackTarget": format_hex(item["callbackTarget"]),
                    "reason": item["argument"]["reason"],
                },
                "callbackExactExportedSymbol": item["callbackExactExportedSymbol"],
                "expectedLifecycleImport": item["expectedLifecycleImport"],
                "expectedLifecycleImportObserved": item["expectedLifecycleImportObserved"],
                "focusCallsInWindow": [
                    {
                        "symbol": call["symbol"],
                        "callsite": format_hex(call["callsite"]),
                        "owner": call["owner"],
                    }
                    for call in item["focusCallsInWindow"]
                ],
            }
            for item in results
        ],
        "decision": {
            "allThreeSetterArgumentsResolved": all_arguments_resolved,
            "threeDistinctCallbackTargets": unique_callback_targets,
            "replacementLifecycleMappingSupported": lifecycle_mapping_supported,
            "nextBroadDecompilationRequired": not lifecycle_mapping_supported,
        },
        "limitations": [
            "The bounded backward dataflow handles gp-GOT loads, register moves, gp-relative addresses, and literals only.",
            "A callback target is not assigned a synthetic function name when no exact exported symbol exists.",
            "The 0x300-byte callback window is a bounded relevance test, not a reconstructed function boundary.",
            "Static call recovery does not prove execution for any particular HTTP request.",
            "No raw disassembly or firmware binary payload is retained.",
            "Static evidence does not authorize router mutation."
        ],
        "stopRule": (
            "If all three callback arguments resolve and the lifecycle mapping is supported, stop native Web-transform analysis "
            "unless a remaining live DNS form-encoding blocker requires deeper semantics."
        ),
    }
    (output / "callback-registration-summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    with (output / "callback-registration-summary.md").open("w", encoding="utf-8") as handle:
        handle.write("# FRITZ Web file-replacement callback registration\n\n")
        handle.write("Sanitized exact-firmware argument recovery from `libcmapi.so::init_webserver`.\n\n")
        handle.write(f"- decodedInstructions: {len(instructions)}\n")
        handle.write(f"- allThreeSetterArgumentsResolved: {str(all_arguments_resolved).lower()}\n")
        handle.write(f"- threeDistinctCallbackTargets: {str(unique_callback_targets).lower()}\n")
        handle.write(f"- replacementLifecycleMappingSupported: {str(lifecycle_mapping_supported).lower()}\n")
        handle.write(f"- nextBroadDecompilationRequired: {str(not lifecycle_mapping_supported).lower()}\n")
        handle.write("\nNo raw disassembly or proprietary firmware payload is retained.\n")


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
