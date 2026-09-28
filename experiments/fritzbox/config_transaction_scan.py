#!/usr/bin/env python3
"""Derive sanitized FRITZ!OS configuration-transaction metadata.

Outputs paths, hashes, identifiers, symbols and dependency edges only. It does not
copy source lines, binaries, firmware payloads, disassembly, or device data.
"""
from __future__ import annotations

import argparse
import hashlib
import pathlib
import re
import subprocess
from collections import Counter
from typing import Iterable

KEYWORDS = (
    "config", "cfg", "commit", "query", "get", "set", "write", "read",
    "notify", "reload", "restart", "validate", "newval", "cmtable", "uimod",
    "ctlmgr", "cmapi", "fbconf", "configd", "generic", "rest", "domain",
    "transaction", "apply", "save", "service",
)
SAFE = re.compile(r"^[A-Za-z0-9_./:+@{}?-]{3,160}$")
IDENT = re.compile(r"[A-Za-z_$][A-Za-z0-9_$.:/-]{2,159}")
FUNC = re.compile(r"(?:\bfunction\s+([A-Za-z_$][A-Za-z0-9_$.:]{1,120})|([A-Za-z_$][A-Za-z0-9_$.:]{1,120})\s*=\s*function\b)")
CALL = re.compile(r"\b([A-Za-z_$][A-Za-z0-9_$.:]{1,120})\s*\(")
REQ = re.compile(r"(?:require\s*\(?\s*[\"']([^\"']+)|from\s+[\"']([^\"']+)|import\s+.*?from\s+[\"']([^\"']+))")

KNOWN_PATHS = (
    "usr/rest_api/api_generic.lua",
    "usr/rest_api/datatype.lua",
    "usr/www/avm/js3/data-controller.js",
    "usr/bin/ctlmgr",
    "usr/bin/ctlmgr_ctl",
    "lib/libcm.so",
    "lib/libcmapi.so",
    "lib/libfbconf.so",
    "lib/libboxnotify.so",
    "lib/libboxnotifycsock.so",
    "usr/share/ctlmgr/libconfigd.so",
    "usr/lib/libserviceinterface.so",
)
MODULE_NAMES = ("newval", "cmtable", "uimod", "opmode")


def wanted(value: str) -> bool:
    low = value.lower()
    return SAFE.match(value) is not None and any(k in low for k in KEYWORDS)


def sha(path: pathlib.Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def run_text(*cmd: str) -> str:
    try:
        return subprocess.run(cmd, check=False, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True).stdout
    except OSError:
        return ""


def write_tsv(path: pathlib.Path, header: Iterable[str], rows: Iterable[Iterable[object]]) -> None:
    with path.open("w", encoding="utf-8") as f:
        f.write("\t".join(header) + "\n")
        for row in rows:
            f.write("\t".join(str(v).replace("\t", " ").replace("\n", " ") for v in row) + "\n")


def is_elf(path: pathlib.Path) -> bool:
    try:
        return path.open("rb").read(4) == b"\x7fELF"
    except OSError:
        return False


def discover(root: pathlib.Path) -> list[pathlib.Path]:
    paths: set[pathlib.Path] = set()
    for rel in KNOWN_PATHS:
        p = root / rel
        if p.is_file():
            paths.add(p)
    for base in (root / "usr/lua", root / "usr/www/avm/lua", root / "usr/rest_api"):
        if not base.exists():
            continue
        for p in base.rglob("*"):
            if p.is_file() and any(name in p.name.lower() for name in MODULE_NAMES):
                paths.add(p)
    # Search a bounded Lua set for module references/definitions when filenames do not reveal them.
    lua_root = root / "usr/lua"
    if lua_root.exists():
        for p in lua_root.rglob("*.lua"):
            try:
                text = p.read_text("utf-8", "replace")
            except OSError:
                continue
            low = text.lower()
            if any(name in low for name in ("cmtable.add_var", "newval.", "uimod.", "ctlmgr")):
                paths.add(p)
    return sorted(paths)


def scan(root: pathlib.Path, output: pathlib.Path) -> None:
    output.mkdir(parents=True, exist_ok=True)
    files = discover(root)
    file_rows=[]; id_rows=set(); func_rows=set(); call_rows=set(); dep_rows=set(); symbol_rows=set(); string_rows=set(); needed_rows=set()
    kinds=Counter()

    for path in files:
        rel=str(path.relative_to(root))
        elf=is_elf(path)
        kinds["elf" if elf else "text"] += 1
        file_rows.append((rel, path.stat().st_size, sha(path), "elf" if elf else "text"))
        if elf:
            symbols = run_text("readelf", "-Ws", str(path))
            for line in symbols.splitlines():
                fields=line.split()
                if not fields:
                    continue
                candidate=fields[-1].split("@",1)[0]
                if wanted(candidate):
                    symbol_rows.add((rel,candidate))
            dynamic = run_text("readelf", "-d", str(path))
            for match in re.finditer(r"Shared library: \[([^\]]+)\]", dynamic):
                needed_rows.add((rel,match.group(1)))
            strings = run_text("strings", "-a", "-n", "5", str(path))
            for value in strings.splitlines():
                value=value.strip()
                if wanted(value):
                    string_rows.add((rel,value))
        else:
            try:
                text=path.read_text("utf-8","replace")
            except OSError:
                continue
            for ident in set(IDENT.findall(text)):
                if wanted(ident):
                    id_rows.add((rel,ident))
            for m in FUNC.finditer(text):
                name=m.group(1) or m.group(2)
                if name and wanted(name): func_rows.add((rel,name))
            for m in CALL.finditer(text):
                name=m.group(1)
                if wanted(name): call_rows.add((rel,name))
            for m in REQ.finditer(text):
                target=next((g for g in m.groups() if g),None)
                if target: dep_rows.add((rel,target))

    write_tsv(output/"focus-files.tsv",("path","bytes","sha256","kind"),file_rows)
    write_tsv(output/"text-identifiers.tsv",("path","identifier"),sorted(id_rows))
    write_tsv(output/"function-identifiers.tsv",("path","function"),sorted(func_rows))
    write_tsv(output/"call-identifiers.tsv",("path","call"),sorted(call_rows))
    write_tsv(output/"text-dependencies.tsv",("path","dependency"),sorted(dep_rows))
    write_tsv(output/"elf-symbols.tsv",("path","symbol"),sorted(symbol_rows))
    write_tsv(output/"elf-needed.tsv",("path","needed"),sorted(needed_rows))
    write_tsv(output/"elf-safe-strings.tsv",("path","identifier"),sorted(string_rows))

    with (output/"summary.md").open("w",encoding="utf-8") as f:
        f.write("# FRITZ!OS configuration transaction engine scan\n\n")
        f.write("Derived identifiers only; no source/binary payload retained.\n\n")
        f.write(f"- focus files: {len(file_rows)}\n- text files: {kinds['text']}\n- ELF files: {kinds['elf']}\n")
        f.write(f"- text identifiers: {len(id_rows)}\n- function identifiers: {len(func_rows)}\n- call identifiers: {len(call_rows)}\n")
        f.write(f"- text dependency edges: {len(dep_rows)}\n- ELF filtered symbols: {len(symbol_rows)}\n- ELF dependency edges: {len(needed_rows)}\n- ELF safe identifier strings: {len(string_rows)}\n")
        f.write("\nStatic evidence only; mutation remains unauthorized.\n")


def main() -> int:
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("root",type=pathlib.Path)
    p.add_argument("--output",type=pathlib.Path,required=True)
    a=p.parse_args(); scan(a.root,a.output); return 0

if __name__ == "__main__":
    raise SystemExit(main())
