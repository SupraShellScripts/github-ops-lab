#!/usr/bin/env python3
"""Emit sanitized candidate evidence for DNS UI/API convergence in FRITZ!OS.

The scan is deliberately narrow: it searches the extracted exact firmware for a
small set of already-evidenced DNS/API/configuration-manager anchors and known
implementation filenames. It emits only paths, hashes, byte counts, anchor names,
match counts, and bounded co-occurrence metadata. No firmware/source payloads or
source lines are retained.
"""
from __future__ import annotations

import argparse
import fnmatch
import hashlib
import json
import pathlib
from collections import defaultdict

MAX_SCAN_BYTES = 32 * 1024 * 1024

ANCHORS: dict[str, tuple[bytes, ...]] = {
    "api-resource": (
        b"generic/dnsserver",
        b"/api/v0/generic/dnsserver",
    ),
    "dns-config-domain": (
        b"dnscfg:settings",
    ),
    "native-ui-write": (
        b"cmtable.add_var",
        b"box.set_config",
    ),
    "dns-dot-variable": (
        b"dns_over_tls_enabled",
        b"dns_over_tls_fqdns",
        b"dns_over_tls_strict",
        b"dns_over_tls_udp_fallback",
    ),
    "generic-api-implementation": (
        b"api_generic",
        b"data-controller",
    ),
    "configuration-manager": (
        b"ctlmgr",
        b"libcm",
        b"libcmapi",
        b"libfbconf",
        b"libconfigd",
    ),
}

PATH_PATTERNS = (
    "*api_generic.lua",
    "*data-controller.js",
    "*cmtable.lua",
    "*newval.lua",
    "*uimod.lua",
    "*/ctlmgr",
    "*/libcm.so*",
    "*/libcmapi.so*",
    "*/libfbconf.so*",
    "*/libconfigd.so*",
)


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def rel(path: pathlib.Path, root: pathlib.Path) -> str:
    return path.relative_to(root).as_posix()


def file_kind(data: bytes) -> str:
    return "binary" if b"\x00" in data[:4096] else "text"


def matches_path_pattern(relative: str) -> list[str]:
    value = "/" + relative
    return sorted(pattern for pattern in PATH_PATTERNS if fnmatch.fnmatch(value, pattern))


def scan(root: pathlib.Path, output: pathlib.Path) -> None:
    output.mkdir(parents=True, exist_ok=True)

    hit_rows: list[tuple[str, str, str, str, str, str, str]] = []
    path_rows: list[tuple[str, str, str, str]] = []
    categories_by_file: dict[str, set[str]] = defaultdict(set)
    anchors_by_file: dict[str, set[str]] = defaultdict(set)
    skipped_large_files = 0

    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        relative = rel(path, root)
        try:
            size = path.stat().st_size
        except OSError:
            continue

        patterns = matches_path_pattern(relative)
        data: bytes | None = None

        # Known implementation filenames remain useful candidates even when no
        # selected anchor string is present in their payload.
        if patterns:
            try:
                data = path.read_bytes()
            except OSError:
                data = None
            if data is not None:
                digest = sha256_bytes(data)
                for pattern in patterns:
                    path_rows.append((relative, str(size), digest, pattern))

        if size > MAX_SCAN_BYTES:
            skipped_large_files += 1
            continue
        if data is None:
            try:
                data = path.read_bytes()
            except OSError:
                continue

        digest: str | None = None
        kind = file_kind(data)
        for category, needles in ANCHORS.items():
            for needle in needles:
                count = data.count(needle)
                if not count:
                    continue
                if digest is None:
                    digest = sha256_bytes(data)
                anchor = needle.decode("ascii")
                hit_rows.append((
                    category,
                    anchor,
                    relative,
                    str(size),
                    digest,
                    str(count),
                    kind,
                ))
                categories_by_file[relative].add(category)
                anchors_by_file[relative].add(anchor)

    cooccurrence_rows: list[tuple[str, str, str]] = []
    for relative in sorted(categories_by_file):
        categories = sorted(categories_by_file[relative])
        if len(categories) < 2:
            continue
        cooccurrence_rows.append((
            relative,
            ",".join(categories),
            ",".join(sorted(anchors_by_file[relative])),
        ))

    def write_tsv(name: str, header: tuple[str, ...], rows) -> None:
        with (output / name).open("w", encoding="utf-8") as handle:
            handle.write("\t".join(header) + "\n")
            for row in rows:
                handle.write("\t".join(str(value).replace("\t", " ") for value in row) + "\n")

    write_tsv(
        "convergence-anchor-hits.tsv",
        ("category", "anchor", "file", "bytes", "sha256", "match_count", "kind"),
        sorted(hit_rows),
    )
    write_tsv(
        "convergence-path-candidates.tsv",
        ("file", "bytes", "sha256", "matched_pattern"),
        sorted(path_rows),
    )
    write_tsv(
        "convergence-cooccurrence.tsv",
        ("file", "categories", "anchors"),
        cooccurrence_rows,
    )

    categories_observed = sorted({row[0] for row in hit_rows})
    summary = {
        "schemaVersion": 1,
        "purpose": "dns-api-native-ui-convergence-candidate-evidence",
        "maxScannedFileBytes": MAX_SCAN_BYTES,
        "anchorHitRows": len(hit_rows),
        "pathCandidateRows": len(path_rows),
        "multiCategoryFileRows": len(cooccurrence_rows),
        "categoriesObserved": categories_observed,
        "criticalQuestion": (
            "Do the native DNS/DoT UI path and generic/dnsserver API path converge "
            "on common AVM configuration-manager transaction machinery?"
        ),
        "interpretation": {
            "apiResourceObserved": "api-resource" in categories_observed,
            "nativeConfigDomainObserved": "dns-config-domain" in categories_observed,
            "nativeUiWriterObserved": "native-ui-write" in categories_observed,
            "configurationManagerCandidateObserved": "configuration-manager" in categories_observed,
            "genericApiImplementationCandidateObserved": "generic-api-implementation" in categories_observed,
            "convergenceProven": False,
        },
        "skippedLargeFiles": skipped_large_files,
        "limitations": [
            "Exact-byte matches and path names are candidate evidence, not call-graph proof.",
            "Same-file co-occurrence is stronger search guidance but does not prove execution flow.",
            "Absence of an anchor does not prove absence of equivalent stripped/encoded behavior.",
            "Static evidence does not authorize live mutation.",
            "No source lines or proprietary payloads are retained.",
        ],
        "nextIfPositive": (
            "Use the smallest matched API/configuration-manager candidate set for focused xref/call analysis."
        ),
        "nextIfNegative": (
            "Treat the negative result as search-space reduction and inspect generic API dispatch/control boundaries rather than broad firmware decompilation."
        ),
    }
    (output / "convergence-summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )

    with (output / "convergence-summary.md").open("w", encoding="utf-8") as handle:
        handle.write("# DNS native-UI / generic-API convergence candidate scan\n\n")
        handle.write("Sanitized static candidate evidence only; convergence remains unproven.\n\n")
        for key in ("anchorHitRows", "pathCandidateRows", "multiCategoryFileRows", "skippedLargeFiles"):
            handle.write(f"- {key}: {summary[key]}\n")
        handle.write("- categoriesObserved: " + ", ".join(categories_observed) + "\n")
        handle.write("\nThe output is intended to select the next focused xref/call-analysis target, not to infer mutation safety.\n")


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
