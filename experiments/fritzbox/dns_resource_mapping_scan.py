#!/usr/bin/env python3
"""Derive sanitized generic/dnsserver -> configuration mapping evidence.

This pass is intentionally narrow. It inspects only the exact firmware's REST
resource declaration and DNS JS data adapters. It emits JSON-pointer locations,
file hashes, matched semantic identifiers, parent-key sets, and bounded semantic
siblings. It never emits source lines or firmware/configuration payloads.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
import re
from typing import Any

RESOURCE_FILE = "etc/rest_api_resources.json"
DATA_FILES = (
    "usr/www/avm/js3/data/dnsserver.data.js",
    "usr/www/avm/js3/data/dnscfg.data.js",
)

EXACT_ANCHORS = (
    "generic/dnsserver",
    "dns_over_tls_enabled",
    "dns_over_tls_fqdns",
    "dns_over_tls_strict",
    "dns_over_tls_udp_fallback",
)
SEMANTIC_TERMS = (
    "dns", "dnscfg", "dnsserver", "dot", "tls", "resolver", "server",
    "firstdns", "seconddns", "fallback", "fqdn", "edns", "dhcpserver_lan_dns",
    "generic", "api_generic", "resource", "module", "uimod", "webvar",
    "settings", "query", "set", "get", "transaction",
)
SAFE_VALUE_RE = re.compile(r"^[A-Za-z0-9_./:{}?&=%+@-]{1,160}$")
STRING_RE = re.compile(r"([\"'])([^\"'\r\n]{1,180})\1")
IDENT_RE = re.compile(r"[A-Za-z_$][A-Za-z0-9_$.:/-]{1,127}")


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def line_digest(line: str) -> str:
    return hashlib.sha256(line.encode("utf-8", "replace")).hexdigest()


def pointer_escape(value: str) -> str:
    return value.replace("~", "~0").replace("/", "~1")


def semantic(value: str) -> bool:
    low = value.lower()
    return any(term in low for term in SEMANTIC_TERMS)


def safe_scalar(value: Any) -> str | None:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return str(value)
    if isinstance(value, str) and SAFE_VALUE_RE.fullmatch(value):
        return value
    return None


def direct_semantic_pairs(node: dict[str, Any]) -> list[str]:
    pairs: list[str] = []
    for key, value in sorted(node.items(), key=lambda item: str(item[0])):
        scalar = safe_scalar(value)
        if scalar is None:
            continue
        if semantic(str(key)) or semantic(scalar):
            pairs.append(f"{key}={scalar}")
    return pairs[:80]


def walk_json(
    node: Any,
    pointer: str,
    dict_ancestors: list[tuple[str, dict[str, Any]]],
    rows: set[tuple[str, ...]],
) -> None:
    if isinstance(node, dict):
        current = (pointer, node)
        ancestors = dict_ancestors + [current]
        for key, value in node.items():
            child = f"{pointer}/{pointer_escape(str(key))}"
            if semantic(str(key)):
                for distance, (ancestor_pointer, ancestor) in enumerate(reversed(ancestors[-3:]), start=0):
                    rows.add((
                        child,
                        f"key:{key}",
                        str(distance),
                        ancestor_pointer,
                        ",".join(sorted(str(k) for k in ancestor.keys())[:120]),
                        ",".join(direct_semantic_pairs(ancestor)),
                    ))
            walk_json(value, child, ancestors, rows)
        return

    if isinstance(node, list):
        for index, value in enumerate(node):
            walk_json(value, f"{pointer}/{index}", dict_ancestors, rows)
        return

    scalar = safe_scalar(node)
    if scalar is None or not semantic(scalar):
        return
    for distance, (ancestor_pointer, ancestor) in enumerate(reversed(dict_ancestors[-3:]), start=0):
        rows.add((
            pointer,
            f"value:{scalar}",
            str(distance),
            ancestor_pointer,
            ",".join(sorted(str(k) for k in ancestor.keys())[:120]),
            ",".join(direct_semantic_pairs(ancestor)),
        ))


def write_tsv(path: pathlib.Path, header: tuple[str, ...], rows) -> None:
    with path.open("w", encoding="utf-8") as handle:
        handle.write("\t".join(header) + "\n")
        for row in rows:
            handle.write("\t".join(str(v).replace("\t", " ").replace("\n", " ") for v in row) + "\n")


def scan(root: pathlib.Path, output: pathlib.Path) -> None:
    output.mkdir(parents=True, exist_ok=True)
    file_rows: list[tuple[str, int, str]] = []
    resource_rows: set[tuple[str, ...]] = set()
    data_rows: set[tuple[str, ...]] = set()

    resource_path = root / RESOURCE_FILE
    if resource_path.is_file():
        raw = resource_path.read_bytes()
        file_rows.append((RESOURCE_FILE, len(raw), digest(raw)))
        try:
            parsed = json.loads(raw.decode("utf-8", "strict"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise SystemExit(f"cannot parse {RESOURCE_FILE}: {exc}")
        walk_json(parsed, "$", [], resource_rows)

    for relative in DATA_FILES:
        path = root / relative
        if not path.is_file():
            continue
        raw = path.read_bytes()
        file_rows.append((relative, len(raw), digest(raw)))
        text = raw.decode("utf-8", "replace")
        for line_number, line in enumerate(text.splitlines(), start=1):
            safe_strings = {
                match.group(2)
                for match in STRING_RE.finditer(line)
                if SAFE_VALUE_RE.fullmatch(match.group(2)) and semantic(match.group(2))
            }
            identifiers = {token for token in IDENT_RE.findall(line) if semantic(token)}
            matched = sorted(set(EXACT_ANCHORS).intersection(safe_strings | identifiers))
            if not matched and "generic/dnsserver" not in safe_strings:
                continue
            data_rows.add((
                relative,
                str(line_number),
                line_digest(line),
                ",".join(matched),
                ",".join(sorted(safe_strings)[:120]),
                ",".join(sorted(identifiers)[:120]),
            ))

    write_tsv(output / "dns-resource-map-files.tsv", ("file", "bytes", "sha256"), sorted(file_rows))
    write_tsv(
        output / "dns-resource-map-json-context.tsv",
        ("match_pointer", "match", "ancestor_distance", "ancestor_pointer", "ancestor_keys", "semantic_direct_scalars"),
        sorted(resource_rows),
    )
    write_tsv(
        output / "dns-resource-map-data-context.tsv",
        ("file", "line", "source_line_sha256", "exact_anchors", "semantic_strings", "semantic_identifiers"),
        sorted(data_rows),
    )

    resource_anchor_counts = {
        anchor: sum(1 for row in resource_rows if anchor in row[1] or anchor in row[5])
        for anchor in EXACT_ANCHORS
    }
    summary = {
        "schemaVersion": 1,
        "purpose": "dns-generic-resource-field-mapping",
        "hypothesis": "dns-api-resource-field-mapping",
        "hypothesisStatus": "unresolved",
        "filesObserved": len(file_rows),
        "resourceContextRows": len(resource_rows),
        "dataContextRows": len(data_rows),
        "resourceAnchorCounts": resource_anchor_counts,
        "decisionRule": (
            "Use only the smallest resource/object contexts that connect generic/dnsserver or DNS fields "
            "to dnscfg/Uimod/web-variable semantics. If the mapping is absent, record the negative and "
            "revise the hypothesis rather than broadening to unrelated firmware."
        ),
        "limitations": [
            "JSON pointers and semantic identifiers are static mapping evidence, not runtime execution proof.",
            "No source lines, arbitrary string payloads, firmware payloads, or router configuration are retained.",
            "Static evidence does not authorize mutation."
        ],
    }
    (output / "dns-resource-map-summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (output / "dns-resource-map-summary.md").write_text(
        "# generic/dnsserver resource mapping\n\n"
        "Sanitized exact-firmware mapping evidence; DNS-specific field mapping remains unresolved until the output is reviewed.\n\n"
        f"- filesObserved: {summary['filesObserved']}\n"
        f"- resourceContextRows: {summary['resourceContextRows']}\n"
        f"- dataContextRows: {summary['dataContextRows']}\n"
        + "".join(f"- {anchor}: {count}\n" for anchor, count in resource_anchor_counts.items()),
        encoding="utf-8",
    )


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
