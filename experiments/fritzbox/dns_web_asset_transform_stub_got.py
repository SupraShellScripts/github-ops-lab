#!/usr/bin/env python3
"""Final bounded resolver for FRITZ Web replacement callback registration.

This wrapper reuses the already-tested symbolic MIPS call tracker from
`dns_web_asset_transform_xrefs.py` and adds exactly one missing MIPS mechanism:
local GOT entries whose Initial value is an imported function's `.MIPS.stubs`
address. It emits only normalized focus relations; raw GOT/disassembly stays in
runner memory and is never retained.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import pathlib
import re

BASE_PATH = pathlib.Path(__file__).with_name("dns_web_asset_transform_xrefs.py")
spec = importlib.util.spec_from_file_location("fritz_xrefs_base", BASE_PATH)
if spec is None or spec.loader is None:
    raise RuntimeError(f"cannot load {BASE_PATH}")
base = importlib.util.module_from_spec(spec)
spec.loader.exec_module(base)

HEX_RE = re.compile(r"(?<![0-9A-Fa-f])([0-9A-Fa-f]{6,8})(?![0-9A-Fa-f])")


def parse_focus_got(text: str, focus_values: dict[int, str]) -> dict[int, tuple[str, str]]:
    resolved: dict[int, tuple[str, str]] = {}
    for line in text.splitlines():
        access = base.GOT_ACCESS_RE.search(line)
        if not access:
            continue
        offset = int(access.group(1), 10)

        for symbol in base.FOCUS:
            if re.search(rf"(?:^|\s){re.escape(symbol)}(?:@\S+)?\s*$", line):
                resolved[offset] = (symbol, "symbolName")
                break
        if offset in resolved:
            continue

        matches = []
        for token in HEX_RE.findall(line):
            value = int(token, 16)
            if value in focus_values:
                matches.append(focus_values[value])
        matches = sorted(set(matches))
        if len(matches) == 1:
            resolved[offset] = (matches[0], "stubInitialValue")
    return resolved


def parser_self_test() -> None:
    sample = """
Primary GOT:
 Canonical gp value: 00188000
 Reserved entries:
  Address     Access  Initial Purpose
 00180010 -32752(gp) 0017f840
 Global entries:
  Address     Access  Initial Sym.Val. Type Ndx Name
 00181924 -26332(gp) 00000000 00180f70 FUNC UND replacement_processing
"""
    values = {
        0x17F840: "websrv_set_file_replacement_init_func",
        0x180F70: "replacement_processing",
    }
    got = parse_focus_got(sample, values)
    assert got[-32752] == ("websrv_set_file_replacement_init_func", "stubInitialValue")
    assert got[-26332] == ("replacement_processing", "symbolName")


def main() -> int:
    base.parser_self_test()
    parser_self_test()

    ap = argparse.ArgumentParser()
    ap.add_argument("root", type=pathlib.Path)
    ap.add_argument("--output", required=True, type=pathlib.Path)
    args = ap.parse_args()
    root = args.root.resolve()
    out = args.output.resolve()
    out.mkdir(parents=True, exist_ok=True)

    cmapi = root / base.CMAPI
    replacement = root / base.REPLACEMENT
    for path in (cmapi, replacement):
        if not path.is_file():
            raise SystemExit(f"required exact-firmware target missing: {path}")

    objdump = base.find_objdump()
    cm_symbols = base.symbol_table(cmapi)
    repl_symbols = base.symbol_table(replacement)
    if base.PRIMARY_FUNCTION not in cm_symbols or cm_symbols[base.PRIMARY_FUNCTION]["ndx"] == "UND":
        raise SystemExit("init_webserver definition not found")

    focus_values = {
        int(rec["value"]): name
        for name, rec in cm_symbols.items()
        if name in base.FOCUS and int(rec["value"]) != 0
    }
    got_detail = parse_focus_got(base.run(["readelf", "-A", str(cmapi)]), focus_values)
    got = {offset: symbol for offset, (symbol, _source) in got_detail.items()}
    instructions = base.disassemble_function(objdump, cmapi, base.PRIMARY_FUNCTION)
    calls = base.analyze_init_webserver(instructions, got, focus_values)

    observed_pairs = {(str(c["target"]), str(c["a0"])) for c in calls if c["a0"]}
    pair_results = {
        setter: ((setter, expected) in observed_pairs)
        for setter, expected in base.EXPECTED.items()
    }
    expected_confirmed = sum(1 for ok in pair_results.values() if ok)
    hypothesis = "confirmed" if expected_confirmed == 3 else "not-confirmed"

    base.write_tsv(
        out / "target-files.tsv",
        ("file", "bytes", "sha256"),
        [
            (base.CMAPI, cmapi.stat().st_size, base.sha256(cmapi)),
            (base.REPLACEMENT, replacement.stat().st_size, base.sha256(replacement)),
        ],
    )
    sym_rows = []
    for file_name, table in ((base.CMAPI, cm_symbols), (base.REPLACEMENT, repl_symbols)):
        for name in sorted(table):
            rec = table[name]
            sym_rows.append((
                file_name, name, f"0x{int(rec['value']):x}", rec["size"],
                rec["type"], rec["bind"], rec["ndx"],
            ))
    base.write_tsv(
        out / "focus-symbols.tsv",
        ("file", "symbol", "value", "size", "type", "bind", "ndx"),
        sym_rows,
    )
    base.write_tsv(
        out / "focus-got.tsv",
        ("gpOffset", "symbol", "resolvedBy"),
        [(offset, got_detail[offset][0], got_detail[offset][1]) for offset in sorted(got_detail)],
    )
    base.write_tsv(
        out / "setter-call-arguments.tsv",
        ("callAddress", "setter", "a0", "a1", "a2", "a3"),
        [
            (f"0x{int(c['address']):x}", c["target"], c["a0"], c["a1"], c["a2"], c["a3"])
            for c in calls
        ],
    )
    base.write_tsv(
        out / "expected-pairs.tsv",
        ("setter", "expectedCallback", "observed"),
        [
            (setter, expected, str(pair_results[setter]).lower())
            for setter, expected in base.EXPECTED.items()
        ],
    )

    by_source: dict[str, int] = {}
    for _symbol, source in got_detail.values():
        by_source[source] = by_source.get(source, 0) + 1

    summary = {
        "scope": "FRITZ!Box 7590 / FRITZ!OS 8.25 exact firmware",
        "primaryFunction": base.PRIMARY_FUNCTION,
        "nativeObjectsObserved": 2,
        "disassembler": pathlib.Path(objdump).name,
        "analysisMethod": "MIPS-GOT-plus-local-stub-initial-value-symbolic-call-arguments",
        "fullDisassemblyRetained": False,
        "parserSelfTestsPassed": True,
        "initWebserverSize": int(cm_symbols[base.PRIMARY_FUNCTION]["size"]),
        "focusGotEntryCount": len(got),
        "focusGotResolutionSources": by_source,
        "setterCallsiteCount": len(calls),
        "expectedSetterCallbackPairsSeen": expected_confirmed,
        "registrationHypothesis": hypothesis,
        "expectedPairs": base.EXPECTED,
        "pairResults": pair_results,
        "mutationAuthorized": False,
        "nextDecision": (
            "stop-native-transform-trace-and-return-to-live-served-checkbox-semantics"
            if hypothesis == "confirmed"
            else "stop-bounded-native-trace-inconclusive-return-to-live-served-checkbox-semantics"
        ),
    }
    (out / "summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    (out / "summary.md").write_text(
        "# FRITZ Web replacement callback xref result\n\n"
        f"- primaryFunction: `{base.PRIMARY_FUNCTION}` ({summary['initWebserverSize']} bytes)\n"
        f"- nativeObjectsObserved: {summary['nativeObjectsObserved']}\n"
        f"- analysisMethod: `{summary['analysisMethod']}`\n"
        f"- focusGotEntryCount: {summary['focusGotEntryCount']}\n"
        f"- focusGotResolutionSources: `{json.dumps(by_source, sort_keys=True)}`\n"
        f"- setterCallsiteCount: {summary['setterCallsiteCount']}\n"
        f"- expectedSetterCallbackPairsSeen: {summary['expectedSetterCallbackPairsSeen']}/3\n"
        f"- registrationHypothesis: **{summary['registrationHypothesis']}**\n"
        f"- nextDecision: `{summary['nextDecision']}`\n"
        "- mutationAuthorized: false\n",
        encoding="utf-8",
    )
    print((out / "summary.md").read_text(encoding="utf-8"))
    print((out / "focus-got.tsv").read_text(encoding="utf-8"))
    print((out / "expected-pairs.tsv").read_text(encoding="utf-8"))
    print((out / "setter-call-arguments.tsv").read_text(encoding="utf-8"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
