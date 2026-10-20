#!/usr/bin/env python3
"""Public-from-birth PST fixture census. No mail fields, content, or PST bytes enter logs.

Only pulls hash-pinned, documented public test fixtures from the stated upstream.
Never use this program on private corpus or claim MAPI/parity acceptance from it.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from urllib.parse import urlparse
from urllib.request import urlopen

UPSTREAM = "justanyone/pypstreader"
REVISION = "857470dfc1ea8c4d03d4d93603401a05c2c8e307"
UPSTREAM_DIR = "tests/fixtures/public"
MAX_BYTES = 1024 * 1024
# Manifest upstream: tests/fixtures/public/MANIFEST.sha256 at REVISION.
# All listed binaries have documented permissive redistribution provenance;
# no binaries are committed, printed, or uploaded by this qualification.
FIXTURES = {
    "javalibpst-dist-list.pst": ("c86841da106036b5abe5a2141dc7644cbb2bf8b504873515eb35a2efeb8c28ac", 271360, 23),
    "pstd-inline-cid.pst": ("5e3aeaed1276cb0560fb08d5f74cebdcc66c3c28615b01194a3db3cfed00ed7b", 29184, 23),
    "pstsdk-sample1.pst": ("9e77f0f7937768506f85eb33b7c114e23ddf3bc7fd5d85226fce56586a8e3618", 271360, 23),
    "pstsdk-sample2.pst": ("587a1ae2785eb218d7d42a98d43ded546aa72670908269d7b3ab25a711a91871", 271360, 14),
    "pstsdk-submessage.pst": ("b619c5c7746e119fbdc6056d0acd70dc3d900a6fba2875570283aec7c3ef73e1", 271360, 23),
    "pstsdk-test_ansi.pst": ("f1ff591b7441f8fcf78cc6c65a78c5d168763338f2fcdf3df5745e742bd66d04", 271360, 14),
    "pstsdk-test_unicode.pst": ("3f2b8ebf011ca754b9c2017d264423e173ef1407f460bd4cefde4a6ccc041f8b", 271360, 23),
    "synth-basics.pst": ("07f0d7f7825782fb40887c4d52cdd58cb37b3750dddb4f8b61feea74c0595982", 35840, 23),
    "tika-variousBodyTypes.pst": ("24c5e6bbb8bf26a817c977283e40e7b69d2661fec0845abbe177f97efcb05fb0", 271360, 23),
}
# Reader smoke is separate from acceptance; these were selected as plain
# baseline stores. A failure is an actual first-failure receipt, not a skip.
READER_BASELINES = {"pstsdk-test_unicode.pst", "pstsdk-test_ansi.pst", "synth-basics.pst"}


def verify_bytes(data: bytes, sha256: str, size: int, version: int) -> None:
    if len(data) != size or len(data) > MAX_BYTES:
        raise ValueError("size mismatch")
    if hashlib.sha256(data).hexdigest() != sha256:
        raise ValueError("SHA256 mismatch")
    if len(data) < 24 or data[:4] != b"!BDN":
        raise ValueError("PST magic mismatch")
    if int.from_bytes(data[10:12], "little") != version:
        raise ValueError("PST wVer mismatch")


def get_bytes(name: str, size: int) -> bytes:
    if name not in FIXTURES:
        raise ValueError("not allowlisted")
    url = f"https://raw.githubusercontent.com/{UPSTREAM}/{REVISION}/{UPSTREAM_DIR}/{name}"
    with urlopen(url, timeout=20) as response:
        effective = urlparse(response.geturl())
        if effective.scheme != "https" or effective.hostname != "raw.githubusercontent.com":
            raise ValueError("unexpected download origin")
        raw = response.read(min(MAX_BYTES, size) + 1)
    if len(raw) > MAX_BYTES:
        raise ValueError("download exceeded byte cap")
    return raw


def selftest() -> None:
    sample = bytearray(32)
    sample[:4] = b"!BDN"
    sample[10:12] = (23).to_bytes(2, "little")
    blob = bytes(sample)
    digest = hashlib.sha256(blob).hexdigest()
    verify_bytes(blob, digest, 32, 23)
    for mutated, sha, size, ver in [
        (blob + b"x", digest, 32, 23),
        (blob, "0" * 64, 32, 23),
        (b"BAD!" + blob[4:], digest, 32, 23),
        (blob, digest, 32, 14),
    ]:
        try:
            verify_bytes(mutated, sha, size, ver)
        except ValueError:
            continue
        raise AssertionError("negative control unexpectedly accepted")
    print("PASS_SELFTEST 1 positive 4 negative; no downloads")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--selftest", action="store_true")
    parser.add_argument("--fetch", action="store_true")
    parser.add_argument("--native", action="store_true")
    args = parser.parse_args()
    if args.selftest:
        selftest()
        if not args.fetch:
            return 0
    if not args.fetch:
        parser.error("pass --selftest or --fetch")
    pff = shutil.which("pffinfo") if args.native else None
    exporter = shutil.which("pffexport") if args.native else None
    if args.native and (pff is None or exporter is None):
        print("MISSING_NATIVE_READER_OR_EXPORTER", file=sys.stderr)
        return 2
    results = []
    with tempfile.TemporaryDirectory(prefix="public-pst-", ignore_cleanup_errors=False) as work:
        for name, (sha256, size, version) in FIXTURES.items():
            # Discard the entire workdir on any failure and never preserve PST bytes.
            data = get_bytes(name, size)
            verify_bytes(data, sha256, size, version)
            row = {"fixture": name, "integrity": "PASS", "version": version, "bytes": size,
                   "sha256": sha256}
            if args.native:
                candidate = Path(work) / name
                candidate.write_bytes(data)
                try:
                    p = subprocess.run([pff, str(candidate)], stdout=subprocess.DEVNULL,
                                       stderr=subprocess.DEVNULL, timeout=20, check=False)
                    row["libpff"] = "PASS" if p.returncode == 0 else "NONZERO"
                    if p.returncode != 0:
                        row["libpff_exit"] = p.returncode
                except subprocess.TimeoutExpired:
                    row["libpff"] = "TIMEOUT"
                # Exercise *distinct* allocated, recovered and complete export modes.
                # Never expose message text or export filenames in the receipt.
                for mode in ("items", "recovered", "all"):
                    target = Path(work) / ("native-" + str(len(results)) + "-" + mode)
                    try:
                        result = subprocess.run(
                            [exporter, "-m", mode, "-t", str(target), str(candidate)],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                            timeout=25, check=False,
                        )
                        row["export_" + mode] = "PASS" if result.returncode == 0 else "NONZERO"
                    except subprocess.TimeoutExpired:
                        row["export_" + mode] = "TIMEOUT"
                    # Count only; never print content, output paths or filenames.
                    roots = [x for x in Path(work).iterdir()
                             if x.name.startswith(target.name + ".") and x.is_dir()]
                    row["export_" + mode + "_files"] = sum(
                        1 for folder in roots for item in folder.rglob("*") if item.is_file()
                    )
                candidate.unlink()
            results.append(row)
    # No message titles, senders, recipients, bodies, or attachment payloads.
    print(json.dumps({"schema": "public-pst-census/v1", "upstream_commit": REVISION,
                      "fixture_count": len(results), "results": results}, sort_keys=True))
    failing = [r["fixture"] for r in results if args.native and
               r["fixture"] in READER_BASELINES and
               (r.get("libpff") != "PASS" or r.get("export_items") != "PASS")]
    if failing:
        print("NATIVE_BASELINE_FIRST_FAILURE: " + ",".join(failing), file=sys.stderr)
        return 3
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError, TimeoutError) as error:
        print(f"PUBLIC_FIXTURE_CENSUS_FAILED: {type(error).__name__}: {error}", file=sys.stderr)
        raise SystemExit(1)
