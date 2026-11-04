# Quartus 25.1 Cyclone IV — toolchain acquisition and admission record

**Scope:** public-safe, original synthetic FPGA pilot only. DE2-115 private program #119/#26 controls acceptance. This document contains public vendor metadata and does not authorize downloading behind vendor authentication, accepting a license, repackaging proprietary assets, or moving private project source into a public runner.

## Exact admission identity

- Edition: Quartus Prime **Lite**
- Release: **25.1std.0 Build 1129**
- Device family: **Cyclone IV E**
- Part: **EP4CE115F29C7**
- Architecture: x86_64 Linux for current Ubuntu runner
- Public pilot workflow: `.github/workflows/quartus25-public-pilot.yml`
- Native `quartus_sh --version` must succeed and show both `Version 25.1std.0 Build 1129` and `Lite Edition`. A wrong edition, older version or missing binary means `TOOL_IDENTITY_BLOCKED` or `ENVIRONMENT_BLOCKED`. Never silently fall back to Standard or Pro.

## Official published inputs (no downloads performed)

Source: https://www.altera.com/downloads/fpga-development-tools/quartus-prime-lite-edition-design-software-version-25-1-linux

| Official item | Filename | Published size | Vendor SHA1 |
| --- | --- | --- | --- |
| Recommended self-extracting installer | `qinst-lite-linux-25.1std-1129.run` | 67.7 MB | `6738aa50c698b894402cf516b10e4c89f5a50fdf` |
| Quartus Lite setup | `QuartusLiteSetup-25.1std.0.1129-linux.run` | 1.9 GB | `ce0773469eacab5b7035c175484625f4ec3737d1` |
| Cyclone IV device support | `cyclone-25.1std.0.1129.qdz` | 466 MB | `835d2b1732549294eed625b692d044135499b5e8` |

These hashes are published vendor metadata, **not** a statement that any file was obtained or checked. The Download link directs to **MyAltera customerlogin sign-in**. The free Lite *license-file* requirement does not imply unrestricted redistribution or permission to accept EULA automatically. Record vendor terms and operator authority before unattended installation.

Only after a lawful installer has been obtained, checked against vendor hashes, installed into a disposable admitted workcell, and its exact edition/version and device database inspected should a native compile be attempted. No installer, device pack or installed tool binary is committed, included in a public source artifact, placed into GHCR, or copied from a private repository.

## Alternatives evaluated, not substituted

- Altera verified publisher Docker repository `alterafpga/quartus-std` offers 25.1std images, but **Standard is not Lite** and the Standard edition requires a separate license; this fails the current edition admission contract.
- Altera official Docker documentation lists Pro and Standard but not Lite official containers. No vendor-provided Lite 25.1 container was established.
- Third-party `chriz2600/quartus-lite` published tags include 23.1.1, which is **not** 25.1 Build 1129. Third-party proprietary binaries also have a distinct provenance and redistribution-review gate.
- Original Icarus and Yosys tests are independently useful without a vendor installer but do not prove Cyclone IV fitting, TimeQuest or a bootable DE2-115 artifact.

## Bounded next mission after tool admission

1. **Observe:** record exact ephemeral public worker identity, CPU/disk/RAM, source SHA, Quartus executable path and `--version`, device availability, official archive SHA1 plus operator-calculated SHA256, and lawful installation evidence. Do not print tokens or raw license files.
2. **Plan:** synthesize only the original public fixture, with explicit QPF/QSF, active SDC, exact part, and no physical pin-ownership claim; estimate disk headroom.
3. **Apply:** execute `python3 scripts/fpga/quartus25_public_pilot.py compile --root fixtures/fpga/quartus25-minimal --out-dir <new-disposable-dir>` with a bounded timeout, within the authorized workcell. Script refuses wrong tool version/edition.
4. **Verify:** independently inspect native map/fit/assembly reports, .sof hash and tool identity. Count `COMPILE_ARTIFACT_OBSERVED` only when executable ran successfully and emitted a .sof. Report TimeQuest setup/hold coverage, WNS/TNS and unconstrained counts **separately**, since wrapper never auto-certifies them. A successful compile on a synthetic unpinned design does not imply a DE2-115 pin/board release.
5. **Rollback:** delete only workcell-owned scratch and generated artifacts; do not remove vendor installations, caches or other actors' outputs unless explicitly scoped.

## Current executed evidence

Native public runner with `quartus_sh` absent, 13/13 Python tests and original Icarus simulation PASS at lab PR #48 head `8fbd693b1f9c9cae47a3f5b84603afb30b339453`:
https://github.com/SupraShellScripts/github-ops-lab/actions/runs/38348849325

Independent Yosys generic synthesis and stand-alone Icarus simulations PASS. Native Quartus install/map/fit/TimeQuest, Zephyr paired images and physical hardware testing **NOT RUN**.

## Operator acquisition and one-shot installation (HOLD until supplied)

The production tool is *not* built from Quartus source. The supported path installs official Altera-distributed binaries. These steps are for a trusted Linux x86_64 actor with an isolated disposable workspace, not for an anonymous public PR runner, and do not transfer vendor binaries into GitHub.

1. Sign in via the [official Altera Lite 25.1 Linux download page](https://www.altera.com/downloads/fpga-development-tools/quartus-prime-lite-edition-design-software-version-25-1-linux) using your own MyAltera account. Download **both** `QuartusLiteSetup-25.1std.0.1129-linux.run` and `cyclone-25.1std.0.1129.qdz`. Do not send credentials, session cookies, or signed URLs to a public repository.
2. Review Altera's actual license terms before installation. The [official installer guide](https://www.intel.com/content/www/us/en/docs/programmable/683472/25-1/command-line-options.html) says unattended installation requires `--accept_eula 1`, an explicit acceptance by the operator. A source test cannot substitute for that authority.
3. Place the two original files together in a **private directory outside the checkout**; do not rename, modify, mirror or upload them to source, public artifacts, GHCR, or shared logs. The following commands are examples that do not accept the EULA or start installation:

```sh
sha1sum /private/path/quartus25-archives/QuartusLiteSetup-25.1std.0.1129-linux.run
sha1sum /private/path/quartus25-archives/cyclone-25.1std.0.1129.qdz
python3 scripts/fpga/quartus25_vendor_install.py inspect \
  --archives /private/path/quartus25-archives \
  --destination /scratch/quartus25-lite
```

An inspect success returns `ARCHIVES_VERIFIED_EULA_PENDING` with both SHA256 digests, the vendor SHA1 matches, available scratch capacity and no side effect on the destination. Anything else is a stop gate; missing or altered archive bytes never count as a compiler failure.

4. **Only after the operator has accepted the vendor's EULA** and explicitly chooses to perform an installation, the actor can execute:

```sh
python3 scripts/fpga/quartus25_vendor_install.py install \
  --archives /private/path/quartus25-archives \
  --destination /scratch/quartus25-lite \
  --accept-altera-eula
```

The program invokes the standalone installer with the documented unattended options, then tests `quartus_sh --version`. Successful output is `TOOL_IDENTITY_VERIFIED_DEVICE_UNCHECKED`, **not** a device-enumeration, fitting or STA claim. Even after successful installation the Cyclone IV package and part availability must be established through a genuine compile; vendor packaging behavior has not yet been qualified on the runner.

5. For a new isolated build-output directory, invoke the existing original public fixture:

```sh
export PATH="/scratch/quartus25-lite/quartus/bin:$PATH"
python3 scripts/fpga/quartus25_public_pilot.py compile \
  --root fixtures/fpga/quartus25-minimal \
  --out-dir /scratch/original-cycloneiv-compile \
  --timeout 900
```

The wrapper fails closed on a non-Lite/non-25.1std Build 1129 edition or absent `.sof`. **A genuine .sof with native compiler exit zero still does not qualify TimeQuest clocks, setup/hold, unconstrained I/O or hardware.** Inspect native reports separately. Only remove owned scratch artifacts; treat failed partial installer state as uncertain until independently examined.

**Public-runners policy:** no official package is downloaded by the automatic public PR workflows. If a future owner authorizes a credential-safe ephemeral vendor-delivery mechanism, design and independently qualify that access path first; never put a reusable vendor-auth token, temporary signed URL, vendor installer layer, or EULA assent inside pull-request-controlled public workflow inputs.

## Local-file admission self-test evidence

The standalone source-only admission script `scripts/fpga/quartus25_vendor_install.py` has an independent, pinned public workflow `.github/workflows/quartus25-vendor-admission-selftest.yml`. Tests use mocked digest checks and sparse fixture files; **no Altera bytes** are downloaded, executed, or published. A passing suite validates only the stated admission behavior, not official installation or compliance with the actual vendor license terms.
