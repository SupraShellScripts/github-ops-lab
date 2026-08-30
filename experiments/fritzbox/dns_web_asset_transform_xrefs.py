#!/usr/bin/env python3
"""Emit bounded exact-firmware call evidence for FRITZ Web file replacement.

This is deliberately not a general decompiler. It inspects exactly two native objects and
one primary registration function selected by the preceding live/static flywheel turn. Raw
firmware, binaries, and full disassembly are never emitted. The implementation interprets
only the MIPS PIC mechanics needed to map focus GOT loads to calls and focus callback
arguments inside libcmapi.so::init_webserver.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
import re
import shutil
import subprocess
from dataclasses import dataclass

CMAPI = "lib/libcmapi.so"
REPLACEMENT = "lib/libreplacement.so.0"
PRIMARY_FUNCTION = "init_webserver"
SETTERS = (
    "websrv_set_file_replacement_init_func",
    "websrv_set_file_replacement_work_func",
    "websrv_set_file_replacement_exit_func",
)
CALLBACKS = (
    "replacement_init_context",
    "replacement_processing",
    "replacement_processing_end",
)
FOCUS = set(SETTERS + CALLBACKS + ("replacement_processing_ex",))
EXPECTED = {
    "websrv_set_file_replacement_init_func": "replacement_init_context",
    "websrv_set_file_replacement_work_func": "replacement_processing",
    "websrv_set_file_replacement_exit_func": "replacement_processing_end",
}

SYM_RE = re.compile(
    r"^\s*\d+:\s+([0-9a-fA-F]+)\s+(\d+)\s+(\S+)\s+(\S+)\s+(\S+)\s+(\S+)\s+(.+?)\s*$"
)
INSN_RE = re.compile(
    r"^\s*([0-9a-fA-F]+):\s+(?:[0-9a-fA-F]{8}\s+)+([A-Za-z0-9_.]+)(?:\s+(.*?))?\s*$"
)
MEM_RE = re.compile(r"^([+-]?(?:0x[0-9a-fA-F]+|\d+))\((\$?[A-Za-z0-9]+)\)$")
GOT_ACCESS_RE = re.compile(r"([+-]?\d+)\(gp\)")

CALLER_SAVED = {
    "v0", "v1", "a0", "a1", "a2", "a3",
    "t0", "t1", "t2", "t3", "t4", "t5", "t6", "t7", "t8", "t9",
}


@dataclass
class Instruction:
    address: int
    mnemonic: str
    operands: str


def run(args: list[str]) -> str:
    cp = subprocess.run(
        args,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        errors="replace",
        check=False,
        timeout=45,
    )
    if cp.returncode != 0:
        raise RuntimeError(f"command failed ({cp.returncode}): {' '.join(args)}\n{cp.stderr}")
    return cp.stdout


def sha256(path: pathlib.Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def symbol_table(path: pathlib.Path) -> dict[str, dict[str, object]]:
    out: dict[str, dict[str, object]] = {}
    for line in run(["readelf", "-Ws", str(path)]).splitlines():
        m = SYM_RE.match(line)
        if not m:
            continue
        value, size, typ, bind, visibility, ndx, name = m.groups()
        name = name.strip().split("@", 1)[0]
        if name not in FOCUS and name != PRIMARY_FUNCTION:
            continue
        record = {
            "value": int(value, 16),
            "size": int(size),
            "type": typ,
            "bind": bind,
            "visibility": visibility,
            "ndx": ndx,
        }
        if name not in out or (out[name]["ndx"] == "UND" and ndx != "UND"):
            out[name] = record
    return out


def find_objdump() -> str:
    for candidate in ("mips-linux-gnu-objdump", "mipsel-linux-gnu-objdump"):
        path = shutil.which(candidate)
        if path:
            return path
    raise RuntimeError("MIPS cross-objdump not found")


def parse_int(text: str) -> int:
    return int(text, 0)


def reg(text: str) -> str:
    return text.strip().lstrip("$")


def got_focus_offsets(path: pathlib.Path) -> dict[int, str]:
    """Recover focus symbol -> gp-relative offsets from the MIPS GOT report.

    GNU readelf -A emits MIPS GOT tables with an Access column such as -32704(gp)
    and the dynamic symbol name. We retain only focus names and their signed offsets.
    """
    text = run(["readelf", "-A", str(path)])
    offsets: dict[int, str] = {}
    for line in text.splitlines():
        matched_symbol = None
        for symbol in FOCUS:
            if re.search(rf"(?:^|\s){re.escape(symbol)}(?:@\S+)?\s*$", line):
                matched_symbol = symbol
                break
        if not matched_symbol:
            continue
        access = GOT_ACCESS_RE.search(line)
        if access:
            offsets[int(access.group(1), 10)] = matched_symbol
    return offsets


def disassemble_function(objdump: str, path: pathlib.Path, function: str) -> list[Instruction]:
    text = run([objdump, "-d", f"--disassemble={function}", str(path)])
    instructions: list[Instruction] = []
    for line in text.splitlines():
        m = INSN_RE.match(line)
        if not m:
            continue
        address, mnemonic, operands = m.groups()
        instructions.append(Instruction(int(address, 16), mnemonic.lower(), operands or ""))
    if not instructions:
        raise RuntimeError(f"no instructions decoded for {function}")
    return instructions


def split_ops(text: str) -> list[str]:
    return [item.strip() for item in text.split(",") if item.strip()]


def apply_symbolic_instruction(ins: Instruction, registers: dict[str, str], got: dict[int, str]) -> None:
    ops = split_ops(ins.operands)
    mnem = ins.mnemonic

    # Focus function pointers imported through the MIPS GOT.
    if mnem in {"lw", "ld"} and len(ops) >= 2:
        dst = reg(ops[0])
        mem = MEM_RE.match(ops[1])
        if mem and reg(mem.group(2)) == "gp":
            offset = parse_int(mem.group(1))
            if offset in got:
                registers[dst] = got[offset]
                return
        registers.pop(dst, None)
        return

    # Common pseudo/copy forms used to move a loaded callback into an argument register.
    if mnem == "move" and len(ops) >= 2:
        dst, src = reg(ops[0]), reg(ops[1])
        if src in registers:
            registers[dst] = registers[src]
        else:
            registers.pop(dst, None)
        return

    if mnem in {"or", "addu", "daddu"} and len(ops) >= 3:
        dst, left, right = reg(ops[0]), reg(ops[1]), reg(ops[2])
        src = None
        if right in {"zero", "0"}:
            src = left
        elif left in {"zero", "0"}:
            src = right
        if src and src in registers:
            registers[dst] = registers[src]
        else:
            registers.pop(dst, None)
        return

    # Conservative kill for instructions that normally write their first operand.
    if mnem in {
        "lui", "li", "la", "addiu", "addi", "daddiu", "andi", "ori", "xori",
        "sll", "srl", "sra", "slt", "sltu", "slti", "sltiu", "subu", "dsubu",
        "mfhi", "mflo",
    } and ops:
        registers.pop(reg(ops[0]), None)


def direct_focus_target(ins: Instruction, values: dict[int, str]) -> str | None:
    if ins.mnemonic not in {"jal", "bal"}:
        return None
    ops = split_ops(ins.operands)
    if not ops:
        return None
    token = ops[0].split()[0]
    token = token.removeprefix("0x")
    try:
        target = int(token, 16)
    except ValueError:
        return None
    return values.get(target)


def analyze_init_webserver(
    instructions: list[Instruction], got: dict[int, str], symbol_values: dict[int, str]
) -> list[dict[str, object]]:
    """Recover only calls to the three focus setters and focus-symbol arguments.

    MIPS executes the instruction after jal/jalr as a delay slot. We therefore snapshot
    arguments after symbolically executing exactly that delay-slot instruction.
    """
    registers: dict[str, str] = {}
    calls: list[dict[str, object]] = []
    pending: tuple[int, str] | None = None

    for ins in instructions:
        if pending is not None:
            apply_symbolic_instruction(ins, registers, got)
            call_address, target = pending
            calls.append({
                "address": call_address,
                "target": target,
                "a0": registers.get("a0"),
                "a1": registers.get("a1"),
                "a2": registers.get("a2"),
                "a3": registers.get("a3"),
            })
            for saved in CALLER_SAVED:
                registers.pop(saved, None)
            pending = None
            continue

        direct = direct_focus_target(ins, symbol_values)
        if direct in SETTERS:
            pending = (ins.address, direct)
            continue

        if ins.mnemonic == "jalr":
            ops = split_ops(ins.operands)
            call_reg = reg(ops[-1]) if ops else "t9"
            target = registers.get(call_reg)
            if target in SETTERS:
                pending = (ins.address, target)
                continue

        apply_symbolic_instruction(ins, registers, got)

    return calls


def write_tsv(path: pathlib.Path, header: tuple[str, ...], rows: list[tuple[object, ...]]) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as f:
        f.write("\t".join(header) + "\n")
        for row in rows:
            f.write("\t".join("" if v is None else str(v).replace("\t", " ").replace("\n", " ") for v in row) + "\n")


def parser_self_test() -> None:
    got = {-100: "replacement_processing", -104: "websrv_set_file_replacement_work_func"}
    values: dict[int, str] = {}
    fixture = [
        Instruction(0x1000, "lw", "a0,-100(gp)"),
        Instruction(0x1004, "lw", "t9,-104(gp)"),
        Instruction(0x1008, "jalr", "t9"),
        Instruction(0x100C, "nop", ""),
    ]
    calls = analyze_init_webserver(fixture, got, values)
    assert calls == [{
        "address": 0x1008,
        "target": "websrv_set_file_replacement_work_func",
        "a0": "replacement_processing",
        "a1": None,
        "a2": None,
        "a3": None,
    }]

    # Also cover callback movement into a0 in a MIPS delay slot.
    got2 = {-100: "replacement_init_context", -104: "websrv_set_file_replacement_init_func"}
    fixture2 = [
        Instruction(0x2000, "lw", "v0,-100(gp)"),
        Instruction(0x2004, "lw", "t9,-104(gp)"),
        Instruction(0x2008, "jalr", "t9"),
        Instruction(0x200C, "move", "a0,v0"),
    ]
    calls2 = analyze_init_webserver(fixture2, got2, values)
    assert calls2[0]["a0"] == "replacement_init_context"


def main() -> int:
    parser_self_test()

    ap = argparse.ArgumentParser()
    ap.add_argument("root", type=pathlib.Path)
    ap.add_argument("--output", required=True, type=pathlib.Path)
    args = ap.parse_args()
    root = args.root.resolve()
    out = args.output.resolve()
    out.mkdir(parents=True, exist_ok=True)

    cmapi = root / CMAPI
    replacement = root / REPLACEMENT
    for p in (cmapi, replacement):
        if not p.is_file():
            raise SystemExit(f"required exact-firmware target missing: {p}")

    objdump = find_objdump()
    cm_symbols = symbol_table(cmapi)
    repl_symbols = symbol_table(replacement)
    if PRIMARY_FUNCTION not in cm_symbols or cm_symbols[PRIMARY_FUNCTION]["ndx"] == "UND":
        raise SystemExit("init_webserver definition not found")

    got = got_focus_offsets(cmapi)
    instructions = disassemble_function(objdump, cmapi, PRIMARY_FUNCTION)
    symbol_values = {
        int(rec["value"]): name
        for name, rec in cm_symbols.items()
        if name in FOCUS and int(rec["value"]) != 0
    }
    calls = analyze_init_webserver(instructions, got, symbol_values)

    observed_pairs = {(str(c["target"]), str(c["a0"])) for c in calls if c["a0"]}
    pair_results = {setter: ((setter, expected) in observed_pairs) for setter, expected in EXPECTED.items()}
    expected_confirmed = sum(1 for ok in pair_results.values() if ok)
    hypothesis = "confirmed" if expected_confirmed == 3 else "not-confirmed"

    write_tsv(
        out / "target-files.tsv",
        ("file", "bytes", "sha256"),
        [(CMAPI, cmapi.stat().st_size, sha256(cmapi)), (REPLACEMENT, replacement.stat().st_size, sha256(replacement))],
    )
    sym_rows = []
    for file_name, table in ((CMAPI, cm_symbols), (REPLACEMENT, repl_symbols)):
        for name in sorted(table):
            rec = table[name]
            sym_rows.append((file_name, name, f"0x{int(rec['value']):x}", rec["size"], rec["type"], rec["bind"], rec["ndx"]))
    write_tsv(out / "focus-symbols.tsv", ("file", "symbol", "value", "size", "type", "bind", "ndx"), sym_rows)
    write_tsv(
        out / "focus-got.tsv",
        ("gpOffset", "symbol"),
        [(offset, got[offset]) for offset in sorted(got)],
    )
    write_tsv(
        out / "setter-call-arguments.tsv",
        ("callAddress", "setter", "a0", "a1", "a2", "a3"),
        [(f"0x{int(c['address']):x}", c["target"], c["a0"], c["a1"], c["a2"], c["a3"]) for c in calls],
    )
    write_tsv(
        out / "expected-pairs.tsv",
        ("setter", "expectedCallback", "observed"),
        [(setter, expected, str(pair_results[setter]).lower()) for setter, expected in EXPECTED.items()],
    )

    summary = {
        "scope": "FRITZ!Box 7590 / FRITZ!OS 8.25 exact firmware",
        "primaryFunction": PRIMARY_FUNCTION,
        "nativeObjectsObserved": 2,
        "disassembler": pathlib.Path(objdump).name,
        "analysisMethod": "MIPS-GOT-symbolic-call-arguments",
        "fullDisassemblyRetained": False,
        "parserSelfTestsPassed": True,
        "initWebserverSize": int(cm_symbols[PRIMARY_FUNCTION]["size"]),
        "focusGotEntryCount": len(got),
        "setterCallsiteCount": len(calls),
        "expectedSetterCallbackPairsSeen": expected_confirmed,
        "registrationHypothesis": hypothesis,
        "expectedPairs": EXPECTED,
        "pairResults": pair_results,
        "mutationAuthorized": False,
        "nextDecision": (
            "stop-native-transform-trace-and-return-to-live-served-checkbox-semantics"
            if hypothesis == "confirmed"
            else "bounded-GOT-pass-did-not-establish-all-pairs-do-not-infer-wire-codec"
        ),
    }
    (out / "summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (out / "summary.md").write_text(
        "# FRITZ Web replacement callback xref result\n\n"
        f"- primaryFunction: `{PRIMARY_FUNCTION}` ({summary['initWebserverSize']} bytes)\n"
        f"- nativeObjectsObserved: {summary['nativeObjectsObserved']}\n"
        f"- analysisMethod: `{summary['analysisMethod']}`\n"
        f"- focusGotEntryCount: {summary['focusGotEntryCount']}\n"
        f"- setterCallsiteCount: {summary['setterCallsiteCount']}\n"
        f"- expectedSetterCallbackPairsSeen: {summary['expectedSetterCallbackPairsSeen']}/3\n"
        f"- registrationHypothesis: **{summary['registrationHypothesis']}**\n"
        f"- nextDecision: `{summary['nextDecision']}`\n"
        "- mutationAuthorized: false\n",
        encoding="utf-8",
    )
    print((out / "summary.md").read_text(encoding="utf-8"))
    print((out / "expected-pairs.tsv").read_text(encoding="utf-8"))
    print((out / "setter-call-arguments.tsv").read_text(encoding="utf-8"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
