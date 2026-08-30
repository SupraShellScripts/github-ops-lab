#!/usr/bin/env python3
"""Recover sanitized MIPS GOT-mediated callsites for the FRITZ Web replacement seam.

The prior generic symbolic-reference pass found zero direct callsites despite exact firmware
dynamic-symbol evidence that libcmapi consumes the target imports. A first GOT-aware pass
recovered the expected MIPS GOT slots but failed to prove that the host objdump decoded any
MIPS instructions. This corrected pass selects an endian-appropriate MIPS cross-objdump,
fails closed if instruction decoding is absent, then resolves allowlisted import GOT entries,
matches gp-relative loads into t9, and associates a bounded subsequent jalr t9 with those
imports. Raw disassembly is ephemeral and never written to output.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
import re
import shutil
import subprocess
from collections import defaultdict

CMAPI = "lib/libcmapi.so"
REPLACEMENT = "lib/libreplacement.so.0"
WEBSRV = "lib/libwebsrv.so.2"
TARGETS = (CMAPI, REPLACEMENT, WEBSRV)

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
FOCUS_SYMBOLS = SETTER_SYMBOLS + PROCESSING_SYMBOLS
TARGET_FUNCTIONS = (
    "init_webserver",
    "set_language_for_webserver",
    "replacement_init_context",
    "replacement_processing",
    "replacement_processing_ex",
    "replacement_processing_end",
)

SYM_RE = re.compile(
    r"^\s*(\d+):\s+([0-9a-fA-F]+)\s+(\d+)\s+(\S+)\s+(\S+)\s+(\S+)\s+(\S+)\s+(.+?)\s*$"
)
MACHINE_RE = re.compile(r"^\s*Machine:\s*(.+?)\s*$", re.MULTILINE)
DATA_RE = re.compile(r"^\s*Data:\s*(.+?)\s*$", re.MULTILINE)
CANONICAL_GP_RE = re.compile(r"Canonical gp value:\s*([0-9a-fA-F]+)", re.IGNORECASE)
GOT_SYMBOL_LINE_RE = re.compile(
    r"^\s*([0-9a-fA-F]+)\s+(-?\d+)\(gp\)\s+([0-9a-fA-F]+)\s+([0-9a-fA-F]+)\s+(\S+)\s+(\S+)\s+(.+?)\s*$"
)
INSN_RE = re.compile(r"^\s*([0-9a-fA-F]+):\s+(?:[0-9a-fA-F]{8}\s+)?(.+?)\s*$")
GP_LOAD_RE = re.compile(r"\b(?:lw|ld)\s+(?:t9|\$25),\s*(-?\d+)\((?:gp|\$28)\)", re.IGNORECASE)
JALR_T9_RE = re.compile(r"\bjalr\s+(?:t9|\$25)\b", re.IGNORECASE)
T9_WRITE_RE = re.compile(r"\b(?:lw|ld|la|li|move|addu|addiu|ori|lui)\s+(?:t9|\$25)\b", re.IGNORECASE)


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def run_text(args: list[str], timeout: int = 120) -> str:
    try:
        cp = subprocess.run(
            args,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            errors="replace",
            check=False,
            timeout=timeout,
        )
    except (OSError, subprocess.TimeoutExpired):
        return ""
    return cp.stdout


def normalized_symbol(name: str) -> str:
    return name.strip().split("@", 1)[0]


def select_mips_objdump(header: str) -> str:
    data_match = DATA_RE.search(header)
    data = data_match.group(1).lower() if data_match else ""
    if "little endian" in data:
        candidate = "mipsel-linux-gnu-objdump"
    elif "big endian" in data:
        candidate = "mips-linux-gnu-objdump"
    else:
        raise RuntimeError(f"cannot determine MIPS ELF endianness from readelf header: {data!r}")
    resolved = shutil.which(candidate)
    if not resolved:
        raise RuntimeError(f"required cross-disassembler not found: {candidate}")
    return resolved


def parse_functions(symbol_text: str) -> list[dict]:
    rows = []
    seen = set()
    for line in symbol_text.splitlines():
        m = SYM_RE.match(line)
        if not m:
            continue
        _idx, value, size, sym_type, bind, visibility, ndx, name = m.groups()
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
    return sorted(candidates, key=lambda f: (f["size"], -f["start"], f["name"]))[0]


def nearest_preceding(functions: list[dict], address: int) -> tuple[dict | None, int | None]:
    candidates = [f for f in functions if f["start"] <= address]
    if not candidates:
        return None, None
    nearest = max(candidates, key=lambda f: f["start"])
    return nearest, address - nearest["start"]


def parse_mips_got(readelf_all: str) -> tuple[int | None, dict[int, dict]]:
    gp_match = CANONICAL_GP_RE.search(readelf_all)
    canonical_gp = int(gp_match.group(1), 16) if gp_match else None
    by_offset: dict[int, dict] = {}
    for line in readelf_all.splitlines():
        m = GOT_SYMBOL_LINE_RE.match(line)
        if not m:
            continue
        address, access, initial, sym_value, sym_type, ndx, name = m.groups()
        name = normalized_symbol(name)
        if name not in FOCUS_SYMBOLS:
            continue
        offset = int(access)
        by_offset[offset] = {
            "symbol": name,
            "gotAddress": int(address, 16),
            "gpOffset": offset,
            "initial": int(initial, 16),
            "symbolValue": int(sym_value, 16),
            "symbolType": sym_type,
            "ndx": ndx,
        }
    return canonical_gp, by_offset


def parse_instructions(disassembly: str) -> list[dict]:
    rows = []
    for line in disassembly.splitlines():
        m = INSN_RE.match(line)
        if not m:
            continue
        address_hex, asm = m.groups()
        try:
            address = int(address_hex, 16)
        except ValueError:
            continue
        asm = asm.strip()
        # Ignore section labels/data dumps accidentally matching the loose line form.
        if not asm or asm.startswith("<"):
            continue
        rows.append({"address": address, "asm": asm})
    return rows


def recover_calls(instructions: list[dict], got_by_offset: dict[int, dict], functions: list[dict]) -> list[dict]:
    calls = []
    for i, insn in enumerate(instructions):
        m = GP_LOAD_RE.search(insn["asm"])
        if not m:
            continue
        gp_offset = int(m.group(1))
        target = got_by_offset.get(gp_offset)
        if target is None:
            continue

        # o32 MIPS PIC conventionally loads the imported callee into t9 from the
        # GOT, prepares arguments, and reaches it with jalr t9. Keep the window
        # bounded and stop if t9 is overwritten first.
        callsite = None
        distance_instructions = None
        for j in range(i + 1, min(i + 17, len(instructions))):
            candidate = instructions[j]
            asm = candidate["asm"]
            if JALR_T9_RE.search(asm):
                callsite = candidate["address"]
                distance_instructions = j - i
                break
            if T9_WRITE_RE.search(asm):
                break
        if callsite is None:
            continue

        owner = find_owner(functions, callsite)
        nearest, distance = nearest_preceding(functions, callsite)
        calls.append({
            "symbol": target["symbol"],
            "gotAddress": target["gotAddress"],
            "gpOffset": gp_offset,
            "loadAddress": insn["address"],
            "callsite": callsite,
            "loadToCallInstructionDistance": distance_instructions,
            "owner": owner["name"] if owner else "<unresolved>",
            "ownerStart": owner["start"] if owner else None,
            "ownerSize": owner["size"] if owner else None,
            "nearestExported": nearest["name"] if nearest else "<none>",
            "nearestExportedStart": nearest["start"] if nearest else None,
            "distanceFromNearestExported": distance,
        })

    dedup = {}
    for row in calls:
        dedup[(row["symbol"], row["callsite"])] = row
    return sorted(dedup.values(), key=lambda r: (r["callsite"], r["symbol"]))


def format_hex(value: int | None) -> str:
    return "" if value is None else f"0x{value:x}"


def write_tsv(path: pathlib.Path, header: tuple[str, ...], rows) -> None:
    with path.open("w", encoding="utf-8") as handle:
        handle.write("\t".join(header) + "\n")
        for row in rows:
            handle.write("\t".join(str(v).replace("\t", " ").replace("\n", " ") for v in row) + "\n")


def scan(root: pathlib.Path, output: pathlib.Path) -> None:
    output.mkdir(parents=True, exist_ok=True)
    file_rows = []
    function_rows = []
    got_rows = []
    call_rows = []
    missing = []
    calls_by_file: dict[str, list[dict]] = {}
    got_by_file: dict[str, dict[int, dict]] = {}
    gp_by_file: dict[str, int | None] = {}
    disassembler_by_file: dict[str, str] = {}
    instruction_counts: dict[str, int] = {}

    for relative in TARGETS:
        path = root / relative
        if not path.is_file():
            missing.append(relative)
            continue
        data = path.read_bytes()
        digest = sha256_bytes(data)
        header = run_text(["readelf", "-hW", str(path)])
        symbol_text = run_text(["readelf", "-Ws", str(path)])
        readelf_all = run_text(["readelf", "-aW", str(path)])
        machine_match = MACHINE_RE.search(header)
        machine = machine_match.group(1).strip() if machine_match else "unknown"
        objdump = select_mips_objdump(header)
        disassembly = run_text([objdump, "-dw", str(path)])
        functions = parse_functions(symbol_text)
        canonical_gp, got_map = parse_mips_got(readelf_all)
        instructions = parse_instructions(disassembly)
        if len(instructions) < 100:
            raise RuntimeError(
                f"cross-disassembly produced too few instructions for {relative}: "
                f"tool={pathlib.Path(objdump).name}, count={len(instructions)}"
            )
        calls = recover_calls(instructions, got_map, functions)

        gp_by_file[relative] = canonical_gp
        got_by_file[relative] = got_map
        calls_by_file[relative] = calls
        disassembler_by_file[relative] = pathlib.Path(objdump).name
        instruction_counts[relative] = len(instructions)
        file_rows.append((
            relative,
            len(data),
            digest,
            machine,
            pathlib.Path(objdump).name,
            len(instructions),
            format_hex(canonical_gp),
            len(got_map),
            len(calls),
        ))

        for fn in functions:
            if fn["name"] in TARGET_FUNCTIONS:
                function_rows.append((relative, fn["name"], format_hex(fn["start"]), fn["size"], format_hex(fn["end"])))
        for offset, entry in sorted(got_map.items()):
            got_rows.append((
                relative,
                entry["symbol"],
                format_hex(entry["gotAddress"]),
                offset,
                format_hex(canonical_gp),
                entry["ndx"],
            ))
        for call in calls:
            call_rows.append((
                relative,
                call["symbol"],
                format_hex(call["gotAddress"]),
                call["gpOffset"],
                format_hex(call["loadAddress"]),
                format_hex(call["callsite"]),
                call["loadToCallInstructionDistance"],
                call["owner"],
                format_hex(call["ownerStart"]),
                call["ownerSize"] if call["ownerSize"] is not None else "",
                call["nearestExported"],
                call["distanceFromNearestExported"] if call["distanceFromNearestExported"] is not None else "",
            ))

    cmapi_calls = calls_by_file.get(CMAPI, [])
    setter_calls = [c for c in cmapi_calls if c["symbol"] in SETTER_SYMBOLS]
    processing_calls = [c for c in cmapi_calls if c["symbol"] in PROCESSING_SYMBOLS]

    setters_by_symbol: dict[str, list[dict]] = defaultdict(list)
    for call in setter_calls:
        setters_by_symbol[call["symbol"]].append(call)

    all_setters_recovered = all(bool(setters_by_symbol[s]) for s in SETTER_SYMBOLS)
    all_setters_in_init = all(
        bool(setters_by_symbol[s]) and all(c["owner"] == "init_webserver" for c in setters_by_symbol[s])
        for s in SETTER_SYMBOLS
    )

    processing_summary = {}
    for symbol in PROCESSING_SYMBOLS:
        rows = [c for c in processing_calls if c["symbol"] == symbol]
        processing_summary[symbol] = {
            "callsiteCount": len(rows),
            "provableOwners": sorted({c["owner"] for c in rows if c["owner"] != "<unresolved>"}),
            "unresolvedCallsites": [format_hex(c["callsite"]) for c in rows if c["owner"] == "<unresolved>"],
            "nearestExportedHints": [
                {
                    "symbol": c["nearestExported"],
                    "distanceBytes": c["distanceFromNearestExported"],
                    "callsite": format_hex(c["callsite"]),
                }
                for c in rows
                if c["owner"] == "<unresolved>" and c["nearestExported"] != "<none>"
            ],
        }

    bounded_regions = sorted({c["owner"] for c in processing_calls if c["owner"] != "<unresolved>"})
    unresolved_processing = sum(1 for c in processing_calls if c["owner"] == "<unresolved>")
    decomp_eligible = bool(
        all_setters_in_init and processing_calls and len(bounded_regions) <= 2 and unresolved_processing == 0
    )

    write_tsv(
        output / "mips-got-elf-files.tsv",
        (
            "file", "bytes", "sha256", "machine", "disassembler", "decoded_instructions",
            "canonical_gp", "focus_got_entries", "recovered_focus_calls"
        ),
        sorted(file_rows),
    )
    write_tsv(
        output / "mips-got-target-functions.tsv",
        ("file", "function", "start", "size", "end"),
        sorted(function_rows),
    )
    write_tsv(
        output / "mips-got-focus-entries.tsv",
        ("file", "symbol", "got_address", "gp_offset", "canonical_gp", "ndx"),
        sorted(got_rows),
    )
    write_tsv(
        output / "mips-got-call-sites.tsv",
        (
            "file", "symbol", "got_address", "gp_offset", "load_address", "callsite",
            "load_to_call_instruction_distance", "provable_owner", "owner_start", "owner_size",
            "nearest_exported_symbol", "distance_from_nearest_exported"
        ),
        sorted(call_rows),
    )

    summary = {
        "schemaVersion": 2,
        "purpose": "probe-informed-mips-got-mediated-web-replacement-call-recovery",
        "targetsRequested": list(TARGETS),
        "targetsObserved": len(file_rows),
        "missingTargets": missing,
        "architectureTechnique": "MIPS PIC global-GOT gp-relative t9 load followed by jalr t9",
        "disassembly": {
            "tools": disassembler_by_file,
            "decodedInstructionCounts": instruction_counts,
            "failClosedMinimumInstructionsPerTarget": 100,
        },
        "canonicalGpRecovered": {k: format_hex(v) for k, v in gp_by_file.items()},
        "focusGotEntries": {
            k: [
                {
                    "symbol": v["symbol"],
                    "gotAddress": format_hex(v["gotAddress"]),
                    "gpOffset": v["gpOffset"],
                }
                for _offset, v in sorted(entries.items())
            ]
            for k, entries in got_by_file.items()
        },
        "hypotheses": {
            "h1CallbackRegistration": {
                "allThreeSetterCallsRecoveredInLibcmapi": all_setters_recovered,
                "allThreeSetterCallsProvablyInsideInitWebserver": all_setters_in_init,
                "calls": [
                    {
                        "symbol": c["symbol"],
                        "loadAddress": format_hex(c["loadAddress"]),
                        "callsite": format_hex(c["callsite"]),
                        "owner": c["owner"],
                    }
                    for c in setter_calls
                ],
            },
            "h2ReplacementProcessingConsumers": processing_summary,
        },
        "decision": {
            "registrationOwnerNarrowed": all_setters_in_init,
            "processingConsumerCallsites": len(processing_calls),
            "processingProvableOwnerRegions": bounded_regions,
            "processingUnresolvedCallsites": unresolved_processing,
            "nextTargetedDecompilationEligible": decomp_eligible,
        },
        "limitations": [
            "Recovered callsites are static MIPS PIC patterns and do not prove runtime execution for a specific HTTP request.",
            "The load-to-jalr matcher is intentionally bounded and may miss more complex compiler sequences.",
            "Containing exported-function ownership is asserted only for callsites inside a defined nonzero symbol range.",
            "Raw disassembly and firmware binary payloads are not retained.",
            "This pass does not prove that replacement processing caused the observed dnsserver.js byte difference.",
            "Static evidence does not authorize router mutation."
        ],
        "nextGate": (
            "If callback registration is owned by init_webserver and replacement consumers reduce to one or two bounded "
            "regions relevant to form semantics, decompile only those regions; otherwise stop or choose the smallest architecture-specific refinement."
        ),
    }
    (output / "mips-got-summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    with (output / "mips-got-summary.md").open("w", encoding="utf-8") as handle:
        handle.write("# FRITZ MIPS GOT-mediated Web callback scan\n\n")
        handle.write("Probe-informed exact-firmware static evidence.\n\n")
        handle.write(f"- targetsObserved: {summary['targetsObserved']}\n")
        handle.write(f"- libcmapiDecodedInstructions: {instruction_counts.get(CMAPI, 0)}\n")
        handle.write(f"- allThreeSetterCallsRecoveredInLibcmapi: {str(all_setters_recovered).lower()}\n")
        handle.write(f"- allThreeSetterCallsProvablyInsideInitWebserver: {str(all_setters_in_init).lower()}\n")
        handle.write(f"- processingConsumerCallsites: {len(processing_calls)}\n")
        handle.write(f"- processingProvableOwnerRegions: {', '.join(bounded_regions) if bounded_regions else '<none>'}\n")
        handle.write(f"- processingUnresolvedCallsites: {unresolved_processing}\n")
        handle.write(f"- nextTargetedDecompilationEligible: {str(decomp_eligible).lower()}\n")
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
