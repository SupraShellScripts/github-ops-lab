#!/usr/bin/env python3
"""Build a sanitized structural map of an extracted FRITZ!OS filesystem.

The output deliberately contains metadata, identifiers, dependency edges, paths,
counts, hashes, and topic associations only. It never copies firmware payloads,
source files, executable contents, credentials, or configuration values.
"""
from __future__ import annotations

import argparse
import collections
import hashlib
import json
import os
import pathlib
import re
import subprocess
from typing import Iterable

TOPICS = {
    "fax": ("fax",),
    "telephony": ("voip", "telefon", "telephony", "tam", "phonebook"),
    "dns": ("dns", "dnssrv", "dot", "dyndns"),
    "certificate": ("certificate", "letsencrypt", "acme", "cert"),
    "vpn": ("wireguard", "vpn", "ipsec"),
    "lan": ("dhcp", "landevice", "ethernet", "route", "portforward"),
    "wifi": ("wlan", "wifi", "wireless", "guest_access"),
    "access": ("parental", "filter", "access_profile"),
    "system": ("backup", "update", "reboot", "event", "ntp"),
    "storage": ("nas", "webdav", "smb", "ftp"),
    "smarthome": ("aha", "smarthome", "dect"),
    "control": ("ctlmgr", "tffs", "tr064", "upnp", "data.lua", "query.lua"),
}

API_RE = re.compile(rb"/api/v0/[A-Za-z0-9_./{}:-]+")
LUA_ENDPOINT_RE = re.compile(rb"/(?:data|query|login_sid)\.lua")
DATA_PAGE_RE = re.compile(
    rb"\bpage\s*(?::|=)\s*[\"']([A-Za-z0-9_.:/-]{2,96})[\"']",
    re.IGNORECASE,
)
LUA_REQUIRE_RE = re.compile(
    rb"\brequire\s*(?:\(\s*)?[\"']([A-Za-z0-9_./-]+)[\"']",
    re.IGNORECASE,
)
JS_IMPORT_RE = re.compile(
    rb"(?:\bfrom\s+|\brequire\s*\(\s*)[\"']([A-Za-z0-9_./@-]+)[\"']",
    re.IGNORECASE,
)
ABS_PATH_RE = re.compile(rb"/(?:usr|bin|sbin|lib|etc|var)/[A-Za-z0-9_./+:-]+")
METHOD_RE = re.compile(rb"\b(GET|POST|PUT|PATCH|DELETE)\b", re.IGNORECASE)
PERSISTENCE_MARKERS = {
    "ctlmgr": b"ctlmgr",
    "tffs": b"tffs",
    "var_flash": b"/var/flash",
    "ar7_cfg": b"ar7.cfg",
    "voip_cfg": b"voip.cfg",
    "wlan_cfg": b"wlan.cfg",
    "data_lua": b"data.lua",
    "query_lua": b"query.lua",
}

TEXT_SUFFIXES = {
    ".lua", ".js", ".html", ".htm", ".sh", ".cfg", ".conf", ".xml",
    ".json", ".txt", ".css", ".cgi", ".asp", ".ini", ".service",
}


def sha256_file(path: pathlib.Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def rel(path: pathlib.Path, root: pathlib.Path) -> str:
    return path.relative_to(root).as_posix()


def run_text(args: list[str]) -> str:
    try:
        cp = subprocess.run(args, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                            check=False, text=True, errors="replace", timeout=20)
        return cp.stdout
    except (OSError, subprocess.TimeoutExpired):
        return ""


def is_elf(path: pathlib.Path) -> bool:
    try:
        with path.open("rb") as f:
            return f.read(4) == b"\x7fELF"
    except OSError:
        return False


def readelf_metadata(path: pathlib.Path) -> dict[str, object]:
    header = run_text(["readelf", "-hW", str(path)])
    program = run_text(["readelf", "-lW", str(path)])
    dynamic = run_text(["readelf", "-dW", str(path)])
    notes = run_text(["readelf", "-nW", str(path)])

    def field(name: str) -> str:
        m = re.search(rf"^\s*{re.escape(name)}:\s*(.+?)\s*$", header, re.MULTILINE)
        return m.group(1) if m else ""

    interp = ""
    m = re.search(r"Requesting program interpreter:\s*([^\]]+)\]", program)
    if m:
        interp = m.group(1).strip()

    needed = sorted(set(re.findall(r"\(NEEDED\).*?\[([^\]]+)\]", dynamic)))
    rpath = ""
    m = re.search(r"\((?:RPATH|RUNPATH)\).*?\[([^\]]+)\]", dynamic)
    if m:
        rpath = m.group(1)
    build_id = ""
    m = re.search(r"Build ID:\s*([0-9a-fA-F]+)", notes)
    if m:
        build_id = m.group(1).lower()

    return {
        "class": field("Class"),
        "data": field("Data"),
        "type": field("Type"),
        "machine": field("Machine"),
        "interpreter": interp,
        "needed": needed,
        "rpath": rpath,
        "buildId": build_id,
    }


def read_bytes_limited(path: pathlib.Path, limit: int = 8 * 1024 * 1024) -> bytes:
    try:
        size = path.stat().st_size
        if size > limit and path.suffix.lower() not in TEXT_SUFFIXES:
            return b""
        return path.read_bytes()
    except OSError:
        return b""


def likely_text(path: pathlib.Path, data: bytes) -> bool:
    if path.suffix.lower() in TEXT_SUFFIXES:
        return True
    if not data:
        return False
    sample = data[:4096]
    if b"\x00" in sample:
        return False
    printable = sum(1 for b in sample if b in b"\t\n\r" or 32 <= b < 127)
    return printable / max(1, len(sample)) > 0.85


def endpoint_methods(data: bytes, start: int, end: int) -> str:
    window = data[max(0, start - 300): min(len(data), end + 300)]
    methods = sorted({m.decode("ascii").upper() for m in METHOD_RE.findall(window)})
    return ",".join(methods) if methods else "unknown"


def scan_root(root: pathlib.Path, report: pathlib.Path) -> None:
    files = [p for p in root.rglob("*") if p.is_file()]
    dirs = [p for p in root.rglob("*") if p.is_dir()]
    top_counts: collections.Counter[str] = collections.Counter()
    ext_counts: collections.Counter[str] = collections.Counter()
    topic_file_counts: collections.Counter[str] = collections.Counter()
    total_bytes = 0
    largest: list[tuple[int, str]] = []

    elf_rows: list[list[str]] = []
    dep_rows: list[list[str]] = []
    topic_binary_rows: list[list[str]] = []
    api_rows: set[tuple[str, str, str]] = set()
    page_rows: set[tuple[str, str]] = set()
    lua_edges: set[tuple[str, str]] = set()
    js_edges: set[tuple[str, str]] = set()
    init_edges: set[tuple[str, str]] = set()
    persistence_rows: list[list[str]] = []
    web_topic_rows: list[list[str]] = []

    path_set = {"/" + rel(p, root) for p in files}

    for path in files:
        rp = rel(path, root)
        try:
            size = path.stat().st_size
        except OSError:
            continue
        total_bytes += size
        first = rp.split("/", 1)[0]
        top_counts[first] += 1
        ext_counts[path.suffix.lower() or "<none>"] += 1
        largest.append((size, rp))

        if is_elf(path):
            meta = readelf_metadata(path)
            elf_rows.append([
                rp, str(size), sha256_file(path), str(meta["class"]), str(meta["data"]),
                str(meta["type"]), str(meta["machine"]), str(meta["interpreter"]),
                str(meta["rpath"]), str(meta["buildId"]),
            ])
            for needed in meta["needed"]:  # type: ignore[index]
                dep_rows.append([rp, str(needed)])

            strings = run_text(["strings", "-a", "-n", "4", str(path)]).lower()
            for topic, needles in TOPICS.items():
                count = sum(strings.count(needle.lower()) for needle in needles)
                if count:
                    topic_binary_rows.append([rp, topic, str(count)])
            continue

        data = read_bytes_limited(path)
        if not likely_text(path, data):
            continue
        low = data.lower()

        # Sanitized topic/file relationships only.
        for topic, needles in TOPICS.items():
            count = sum(low.count(n.encode("ascii")) for n in needles)
            if count:
                topic_file_counts[topic] += 1
                web_topic_rows.append([topic, rp, str(count)])

        for match in API_RE.finditer(data):
            api_rows.add((rp, match.group().decode("utf-8", "replace"),
                          endpoint_methods(data, match.start(), match.end())))
        for match in LUA_ENDPOINT_RE.finditer(data):
            api_rows.add((rp, match.group().decode("utf-8", "replace"),
                          endpoint_methods(data, match.start(), match.end())))
        for match in DATA_PAGE_RE.finditer(data):
            page_rows.add((rp, match.group(1).decode("utf-8", "replace")))
        for match in LUA_REQUIRE_RE.finditer(data):
            lua_edges.add((rp, match.group(1).decode("utf-8", "replace")))
        if path.suffix.lower() == ".js":
            for match in JS_IMPORT_RE.finditer(data):
                js_edges.add((rp, match.group(1).decode("utf-8", "replace")))

        # Service/init graph: only retain references to paths that exist in this image.
        if rp.startswith(("etc/init.d/", "etc/boot.d/", "etc/rc.")) or path.suffix == ".sh":
            for raw in ABS_PATH_RE.findall(data):
                target = raw.decode("utf-8", "replace").rstrip(".,;:)]}")
                if target in path_set:
                    init_edges.add((rp, target.lstrip("/")))

        for marker, needle in PERSISTENCE_MARKERS.items():
            count = low.count(needle.lower())
            if count:
                persistence_rows.append([marker, rp, str(count)])

    largest.sort(reverse=True)
    report.mkdir(parents=True, exist_ok=True)

    def write_tsv(name: str, header: Iterable[str], rows: Iterable[Iterable[str]]) -> None:
        with (report / name).open("w", encoding="utf-8") as f:
            f.write("\t".join(header) + "\n")
            for row in rows:
                f.write("\t".join(row) + "\n")

    write_tsv("elf-inventory.tsv",
              ["path", "bytes", "sha256", "class", "data", "type", "machine",
               "interpreter", "rpath", "build_id"], sorted(elf_rows))
    write_tsv("elf-dependencies.tsv", ["elf", "needed"], sorted(dep_rows))
    write_tsv("binary-topic-matrix.tsv", ["elf", "topic", "match_count"],
              sorted(topic_binary_rows))
    write_tsv("web-endpoints.tsv", ["file", "endpoint", "nearby_http_methods"],
              sorted(api_rows))
    write_tsv("data-lua-pages.tsv", ["file", "page_identifier"], sorted(page_rows))
    write_tsv("lua-require-edges.tsv", ["file", "module"], sorted(lua_edges))
    write_tsv("js-import-edges.tsv", ["file", "module"], sorted(js_edges))
    write_tsv("init-exec-edges.tsv", ["script", "image_path_target"], sorted(init_edges))
    write_tsv("persistence-references.tsv", ["marker", "file", "match_count"],
              sorted(persistence_rows))
    write_tsv("topic-file-matrix.tsv", ["topic", "file", "match_count"],
              sorted(web_topic_rows))

    summary = {
        "schemaVersion": 1,
        "root": root.name,
        "files": len(files),
        "directories": len(dirs),
        "bytes": total_bytes,
        "elfFiles": len(elf_rows),
        "elfDependencyEdges": len(dep_rows),
        "webEndpointOccurrences": len(api_rows),
        "dataLuaPageIdentifiers": len(page_rows),
        "luaDependencyEdges": len(lua_edges),
        "jsDependencyEdges": len(js_edges),
        "initExecEdges": len(init_edges),
        "persistenceReferenceRows": len(persistence_rows),
        "topLevelFileCounts": dict(sorted(top_counts.items())),
        "extensionCounts": dict(sorted(ext_counts.items())),
        "topicFileCounts": dict(sorted(topic_file_counts.items())),
        "largestFiles": [{"bytes": size, "path": path} for size, path in largest[:50]],
    }
    (report / "filesystem-summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )

    machines = collections.Counter(row[6] for row in elf_rows)
    interpreters = collections.Counter(row[7] or "<none>" for row in elf_rows)
    api_unique = sorted({row[1] for row in api_rows})
    pages_unique = sorted({row[1] for row in page_rows})

    with (report / "summary.md").open("w", encoding="utf-8") as f:
        f.write("# FRITZ!OS deep structural map\n\n")
        f.write("Sanitized static-analysis output: paths, identifiers, dependency edges, counts and hashes only.\n\n")
        f.write(f"- Files: {len(files)}\n- Directories: {len(dirs)}\n")
        f.write(f"- ELF binaries/libraries: {len(elf_rows)}\n")
        f.write(f"- ELF dependency edges: {len(dep_rows)}\n")
        f.write(f"- Web endpoint rows: {len(api_rows)}\n")
        f.write(f"- data.lua page identifiers: {len(page_rows)}\n")
        f.write(f"- Init/script image-path edges: {len(init_edges)}\n")
        f.write(f"- Persistence/control reference rows: {len(persistence_rows)}\n\n")
        f.write("## ELF machine types\n\n")
        for name, count in machines.most_common():
            f.write(f"- {name}: {count}\n")
        f.write("\n## ELF interpreters\n\n")
        for name, count in interpreters.most_common():
            f.write(f"- {name}: {count}\n")
        f.write("\n## Distinct Web/API endpoint identifiers\n\n")
        for endpoint in api_unique:
            f.write(f"- `{endpoint}`\n")
        f.write("\n## Distinct data.lua page identifiers\n\n")
        for page in pages_unique:
            f.write(f"- `{page}`\n")
        f.write("\n## Topic coverage\n\n")
        for topic, count in sorted(topic_file_counts.items()):
            f.write(f"- {topic}: {count} text/UI files\n")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("root", type=pathlib.Path)
    parser.add_argument("report", type=pathlib.Path)
    args = parser.parse_args()
    if not args.root.is_dir():
        raise SystemExit(f"root is not a directory: {args.root}")
    scan_root(args.root.resolve(), args.report.resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
