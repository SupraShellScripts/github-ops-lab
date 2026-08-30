#!/usr/bin/env python3
"""Emit sanitized generic/dnsserver -> DNS module/field mapping evidence.

This pass intentionally examines only the exact firmware resource registry and the
DNS data adapter. It emits JSON pointers, key names, bounded semantic scalar
identifiers, file hashes, line numbers/hashes, and exact anchor names. It never
retains source lines, arbitrary string payloads, firmware payloads, or router data.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
import re
from typing import Any

RESOURCE_FILE = "etc/rest_api_resources.json"
DATA_FILE = "usr/www/avm/js3/data/dnsserver.data.js"

EXACT_ANCHORS = (
    "generic/dnsserver",
    "api_generic",
    "dnscfg",
    "dns_over_tls_enabled",
    "dns_over_tls_fqdns",
    "dns_over_tls_strict",
    "dns_over_tls_udp_fallback",
    "ipv4_use_user_dns",
    "ipv4_user_firstdns",
    "ipv4_user_seconddns",
    "ipv6_use_user_dns",
    "ipv6_user_firstdns",
    "ipv6_user_seconddns",
)

SEMANTIC_TERMS = (
    "dns", "dot", "tls", "dnscfg", "api", "generic", "resource", "handler",
    "module", "field", "webvar", "query", "set", "get", "read", "write",
    "server", "ipv4", "ipv6", "fallback", "fqdn",
)

SAFE_SCALAR_RE = re.compile(r"^[A-Za-z0-9_./:{}?&=%+@-]{1,160}$")
IDENT_RE = re.compile(r"[A-Za-z_$][A-Za-z0-9_$.:/-]{1,127}")
STRING_RE = re.compile(r"([\"'])([^\"'\r\n]{1,180})\1")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", "replace")).hexdigest()


def pointer_escape(part: str) -> str:
    return part.replace("~", "~0").replace("/", "~1")


def semantic(value: str) -> bool:
    low = value.lower()
    return any(term in low for term in SEMANTIC_TERMS)


def safe_scalar(value: Any) -> str | None:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return str(value)
    if not isinstance(value, str):
        return None
    value = value.strip()
    if not value or not SAFE_SCALAR_RE.fullmatch(value):
        return None
    if value in EXACT_ANCHORS or semantic(value):
        return value
    return None


def iter_json(node: Any, pointer: str = "$"):
    yield pointer, node
    if isinstance(node, dict):
        for key, value in node.items():
            child = f"{pointer}/{pointer_escape(str(key))}"
            yield from iter_json(value, child)
    elif isinstance(node, list):
        for index, value in enumerate(node):
            child = f"{pointer}/{index}"
            yield from iter_json(value, child)


def parent_pointer(pointer: str) -> str | None:
    if pointer == "$":
        return None
    return pointer.rsplit("/", 1)[0]


def lookup(root: Any, pointer: str) -> Any:
    if pointer == "$":
        return root
    node = root
    for raw in pointer[2:].split("/"):
        part = raw.replace("~1", "/").replace("~0", "~")
        if isinstance(node, list):
            node = node[int(part)]
        else:
            node = node[part]
    return node


def direct_semantic_scalars(obj: Any) -> list[str]:
    if not isinstance(obj, dict):
        return []
    rows = []
    for key, value in obj.items():
        scalar = safe_scalar(value)
        if scalar is not None:
            rows.append(f"{key}={scalar}")
        elif isinstance(value, str) and semantic(str(key)) and SAFE_SCALAR_RE.fullmatch(value.strip()):
            rows.append(f"{key}={value.strip()}")
    return sorted(set(rows))


def json_matches(root: Any):
    rows = []
    seen = set()
    for pointer, node in iter_json(root):
        match = None
        if isinstance(node, str) and node in EXACT_ANCHORS:
            match = f"value:{node}"
        elif pointer != "$":
            last = pointer.rsplit("/", 1)[-1].replace("~1", "/").replace("~0", "~")
            if last in EXACT_ANCHORS or semantic(last):
                match = f"key:{last}"
        if match is None:
            continue
        current = parent_pointer(pointer)
        for distance in range(0, 4):
            if current is None:
                break
            obj = lookup(root, current)
            if isinstance(obj, dict):
                direct_keys = sorted(str(k) for k in obj.keys())
                scalars = direct_semantic_scalars(obj)
                row = (
                    pointer,
                    match,
                    str(distance),
                    current,
                    ",".join(direct_keys[:80]),
                    ",".join(scalars[:120]),
                )
                if row not in seen:
                    seen.add(row)
                    rows.append(row)
            current = parent_pointer(current)
    return sorted(rows)


def find_resource_objects(root: Any):
    rows = []
    seen = set()
    for pointer, node in iter_json(root):
        if not isinstance(node, dict):
            continue
        direct_values = {value for value in node.values() if isinstance(value, str)}
        if "generic/dnsserver" not in direct_values:
            continue
        for key, value in node.items():
            scalar = safe_scalar(value)
            if scalar is not None:
                row = (pointer, str(key), scalar)
                if row not in seen:
                    seen.add(row)
                    rows.append(row)
        for child_pointer, child in iter_json(node, pointer):
            if child_pointer == pointer or not isinstance(child, str):
                continue
            scalar = safe_scalar(child)
            if scalar is None:
                continue
            key = child_pointer.rsplit("/", 1)[-1].replace("~1", "/").replace("~0", "~")
            row = (pointer, child_pointer, f"{key}={scalar}")
            if row not in seen:
                seen.add(row)
                rows.append(row)
    return sorted(rows)


def data_context(path: pathlib.Path):
    data = path.read_bytes()
    text = data.decode("utf-8", "replace")
    rows = []
    for line_no, line in enumerate(text.splitlines(), start=1):
        anchors = sorted(anchor for anchor in EXACT_ANCHORS if anchor in line)
        if not anchors:
            continue
        strings = []
        for match in STRING_RE.finditer(line):
            value = match.group(2).strip()
            if SAFE_SCALAR_RE.fullmatch(value) and (value in EXACT_ANCHORS or semantic(value)):
                strings.append(value)
        ids = sorted({token for token in IDENT_RE.findall(line) if token in EXACT_ANCHORS or semantic(token)})
        rows.append((
            DATA_FILE,
            str(line_no),
            sha256_text(line),
            ",".join(anchors),
            ",".join(sorted(set(strings))[:120]),
            ",".join(ids[:160]),
        ))
    return rows


def write_tsv(path: pathlib.Path, header: tuple[str, ...], rows) -> None:
    with path.open("w", encoding="utf-8") as handle:
        handle.write("\t".join(header) + "\n")
        for row in rows:
            handle.write("\t".join(str(v).replace("\t", " ").replace("\n", " ") for v in row) + "\n")


def scan(root: pathlib.Path, output: pathlib.Path) -> None:
    output.mkdir(parents=True, exist_ok=True)
    resource_path = root / RESOURCE_FILE
    data_path = root / DATA_FILE
    if not resource_path.is_file():
        raise SystemExit(f"missing exact resource registry: {RESOURCE_FILE}")
    if not data_path.is_file():
        raise SystemExit(f"missing exact DNS data adapter: {DATA_FILE}")

    resource_bytes = resource_path.read_bytes()
    data_bytes = data_path.read_bytes()
    try:
        resource_json = json.loads(resource_bytes.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SystemExit(f"resource registry is not parseable JSON: {exc}")

    files = [
        (RESOURCE_FILE, len(resource_bytes), sha256_bytes(resource_bytes)),
        (DATA_FILE, len(data_bytes), sha256_bytes(data_bytes)),
    ]
    contexts = json_matches(resource_json)
    resource_rows = find_resource_objects(resource_json)
    data_rows = data_context(data_path)

    write_tsv(output / "dns-resource-map-files.tsv", ("file", "bytes", "sha256"), files)
    write_tsv(
        output / "dns-resource-map-json-context.tsv",
        ("match_pointer", "match", "ancestor_distance", "ancestor_pointer", "ancestor_keys", "semantic_direct_scalars"),
        contexts,
    )
    write_tsv(
        output / "dns-resource-map-resource-object.tsv",
        ("resource_pointer", "field_or_pointer", "semantic_value"),
        resource_rows,
    )
    write_tsv(
        output / "dns-resource-map-data-context.tsv",
        ("file", "line", "source_line_sha256", "exact_anchors", "semantic_strings", "semantic_identifiers"),
        data_rows,
    )

    counts = {anchor: 0 for anchor in EXACT_ANCHORS}
    for row in contexts:
        joined = "\t".join(row)
        for anchor in EXACT_ANCHORS:
            counts[anchor] += joined.count(anchor)
    for row in data_rows:
        joined = "\t".join(row)
        for anchor in EXACT_ANCHORS:
            counts[anchor] += joined.count(anchor)

    summary = {
        "schemaVersion": 1,
        "purpose": "dns-generic-resource-field-mapping",
        "hypothesis": "dns-api-resource-field-mapping",
        "hypothesisStatus": "unresolved",
        "filesObserved": len(files),
        "resourceContextRows": len(contexts),
        "resourceObjectRows": len(resource_rows),
        "dataContextRows": len(data_rows),
        "anchorObservationCounts": counts,
        "limitations": [
            "JSON pointers and semantic identifiers are static mapping evidence, not runtime execution proof.",
            "No source lines, arbitrary string payloads, firmware payloads, credentials, or router configuration are retained.",
            "Static evidence does not authorize mutation."
        ],
        "decisionRule": (
            "Support static DNS convergence only if the exact generic/dnsserver resource object binds to "
            "api_generic and the DNS configuration module/fields consistent with the native dnscfg path; "
            "otherwise retain or refute the hypothesis without broadening the search."
        ),
    }
    (output / "dns-resource-map-summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    lines = [
        "# generic/dnsserver resource mapping",
        "",
        "Sanitized exact-firmware mapping evidence; resource-specific convergence remains unresolved until reviewed.",
        "",
        f"- filesObserved: {summary['filesObserved']}",
        f"- resourceContextRows: {summary['resourceContextRows']}",
        f"- resourceObjectRows: {summary['resourceObjectRows']}",
        f"- dataContextRows: {summary['dataContextRows']}",
    ]
    for anchor in EXACT_ANCHORS:
        lines.append(f"- {anchor}: {counts[anchor]}")
    (output / "dns-resource-map-summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


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
