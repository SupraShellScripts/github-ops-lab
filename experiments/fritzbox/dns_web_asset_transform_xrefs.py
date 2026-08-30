#!/usr/bin/env python3
"""Emit bounded exact-firmware xref evidence for FRITZ Web file replacement.

This is deliberately not a general decompiler. It inspects exactly two native objects and
one primary registration function selected by the preceding live/static flywheel turn. Raw
firmware, binaries, and full disassembly are never emitted. Output contains hashes, symbol
metadata, focus relocations, and a compact relation test for the callback registration
hypothesis.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
import re
import subprocess

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

RELOC_RE = re.compile(r"^\s*([0-9a-fA-F]+):\s+(R_MIPS_[A-Z0-9_]+)\s+([^\s+]+)")
SYM_RE = re.compile(
    r"^\s*\d+:\s+([0-9a-fA-F]+)\s+(\d+)\s+(\S+)\s+(\S+)\s+(\S+)\s+(\S+)\s+(.+?)\s*$"
)


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
        # Prefer a definition over an undefined dynamic-symbol duplicate.
        if name not in out or (out[name]["ndx"] == "UND" and ndx != "UND"):
            out[name] = record
    return out


def relocs_for_function(path: pathlib.Path, function: str) -> list[dict[str, object]]:
    text = run(["objdump", "-drw", f"--disassemble={function}", str(path)])
    rows = []
    for line in text.splitlines():
        m = RELOC_RE.match(line)
        if not m:
            continue
        off, reloc_type, symbol = m.groups()
        symbol = symbol.split("@", 1)[0]
        rows.append({"offset": int(off, 16), "relocation": reloc_type, "symbol": symbol})
    return rows


def write_tsv(path: pathlib.Path, header: tuple[str, ...], rows: list[tuple[object, ...]]) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as f:
        f.write("\t".join(header) + "\n")
        for row in rows:
            f.write("\t".join(str(v).replace("\t", " ").replace("\n", " ") for v in row) + "\n")


def main() -> int:
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

    cm_symbols = symbol_table(cmapi)
    repl_symbols = symbol_table(replacement)
    if PRIMARY_FUNCTION not in cm_symbols or cm_symbols[PRIMARY_FUNCTION]["ndx"] == "UND":
        raise SystemExit("init_webserver definition not found")

    init_relocs = relocs_for_function(cmapi, PRIMARY_FUNCTION)
    focus_relocs = [r for r in init_relocs if r["symbol"] in FOCUS]

    # MIPS PIC code normally leaves dynamic-symbol relocations near the load/call sites.
    # For each setter, look only 0x100 bytes backwards for callback-symbol references.
    contexts = []
    expected_confirmed = 0
    for setter in SETTERS:
        setter_offsets = [int(r["offset"]) for r in focus_relocs if r["symbol"] == setter]
        for setter_offset in setter_offsets:
            nearby = sorted({
                str(r["symbol"])
                for r in focus_relocs
                if int(r["offset"]) <= setter_offset
                and int(r["offset"]) >= setter_offset - 0x100
                and r["symbol"] in CALLBACKS
            })
            expected = EXPECTED[setter]
            confirmed = expected in nearby
            expected_confirmed += int(confirmed)
            contexts.append((
                setter,
                f"0x{setter_offset:x}",
                expected,
                "true" if confirmed else "false",
                ",".join(nearby),
            ))

    hypothesis = "confirmed" if expected_confirmed == 3 and len(contexts) == 3 else "not-confirmed"

    # Second-function budget: characterize only replacement_processing by its dynamic
    # relocation/call vocabulary. This is used only to distinguish a real processing seam
    # from a dead/unrelated exported symbol, without publishing disassembly.
    processing_relocs = relocs_for_function(replacement, "replacement_processing")
    processing_symbols = sorted({str(r["symbol"]) for r in processing_relocs})

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
        out / "init-webserver-focus-relocations.tsv",
        ("offset", "relocation", "symbol"),
        [(f"0x{int(r['offset']):x}", r["relocation"], r["symbol"]) for r in focus_relocs],
    )
    write_tsv(
        out / "setter-callback-context.tsv",
        ("setter", "setterOffset", "expectedCallback", "expectedSeenWithin0x100BeforeSetter", "callbackRefsWithinWindow"),
        contexts,
    )
    write_tsv(
        out / "replacement-processing-relocations.tsv",
        ("symbol",),
        [(s,) for s in processing_symbols],
    )

    summary = {
        "scope": "FRITZ!Box 7590 / FRITZ!OS 8.25 exact firmware",
        "primaryFunction": PRIMARY_FUNCTION,
        "nativeObjectsObserved": 2,
        "fullDisassemblyRetained": False,
        "initWebserverSize": int(cm_symbols[PRIMARY_FUNCTION]["size"]),
        "focusRelocationCount": len(focus_relocs),
        "setterCallsiteCount": len(contexts),
        "expectedSetterCallbackPairsSeen": expected_confirmed,
        "registrationHypothesis": hypothesis,
        "expectedPairs": EXPECTED,
        "replacementProcessingRelocationSymbolCount": len(processing_symbols),
        "mutationAuthorized": False,
        "nextDecision": (
            "stop-native-transform-trace-and-return-to-live-served-checkbox-semantics"
            if hypothesis == "confirmed"
            else "registration-mapping-remains-unresolved-do-not-infer-wire-codec"
        ),
    }
    (out / "summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (out / "summary.md").write_text(
        "# FRITZ Web replacement callback xref result\n\n"
        f"- primaryFunction: `{PRIMARY_FUNCTION}` ({summary['initWebserverSize']} bytes)\n"
        f"- nativeObjectsObserved: {summary['nativeObjectsObserved']}\n"
        f"- setterCallsiteCount: {summary['setterCallsiteCount']}\n"
        f"- expectedSetterCallbackPairsSeen: {summary['expectedSetterCallbackPairsSeen']}/3\n"
        f"- registrationHypothesis: **{summary['registrationHypothesis']}**\n"
        f"- nextDecision: `{summary['nextDecision']}`\n"
        "- mutationAuthorized: false\n",
        encoding="utf-8",
    )
    print((out / "summary.md").read_text(encoding="utf-8"))
    print((out / "setter-callback-context.tsv").read_text(encoding="utf-8"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
