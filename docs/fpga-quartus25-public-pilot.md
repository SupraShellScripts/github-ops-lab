# Quartus Lite 25.1 public-safe execution pilot

This is a standalone original Cyclone IV E experiment, **not** a DE2-115 source projection, physical pin mapping, second source authority, vendor-tool redistribution, or release. It uses original synthetic Verilog/QPF/QSF/SDC targeting `EP4CE115F29C7`. The intended vendor version is Quartus Prime Lite **25.1std.0.1129**.

## D/O -> P -> A -> V

1. **Discover/Observe:** `python3 scripts/fpga/quartus25_public_pilot.py probe --root fixtures/fpga/quartus25-minimal` reports OS, CPU, scratch disk, installed tool presence, SHA256 inputs and honest NOT_RUN stage statuses.
2. **Plan:** `check` validates the exact synthetic QPF/QSF, an active primary-clock SDC, and source files. This does **not** prove complete STA/IO/CDC or physical pin assignments.
3. **Apply:** public Actions checks and simulates original source on a disposable standard Linux runner, with read-only token permissions.
4. **Verify:** compare commit, files/digests, executed job steps, Icarus output, and tool identity. Distinguish SOURCE_CONTRACT_PASS/SIM_PASS from Quartus map, fit, timing, Zephyr and HIL stages.
5. **Rollback:** the runner is disposable; no hardware, private state, or production repository is modified.

Source tests:

```sh
python3 -m unittest discover -s tests -p test_quartus25_public_pilot.py -v
python3 scripts/fpga/quartus25_public_pilot.py check --root fixtures/fpga/quartus25-minimal
```

## Optional Quartus execution after separate authorized setup

An actor that has lawfully obtained and installed official 25.1 Quartus and Cyclone IV device support may run:

```sh
python3 scripts/fpga/quartus25_public_pilot.py compile --root fixtures/fpga/quartus25-minimal --out-dir single-use-results --timeout 900
```

Exit 3 means `quartus_sh` absent and **NOT RUN**. Exit 4 means a real compiler attempt failed or timed out. Exit 0 requires `quartus_sh --flow compile synthetic` to return zero and emit `.sof`. Even `COMPILE_ARTIFACT_OBSERVED` does not prove complete TimeQuest coverage, WNS/TNS, pinout, OS or HIL. Generated artifacts must not be published without independent terms/redistribution review.

Official source: https://www.altera.com/downloads/fpga-development-tools/quartus-prime-lite-edition-design-software-version-25-1-linux . Workflow deliberately does not download installers through guessed links, accept vendor EULA, redistribute vendor packages or create a proprietary OCI image. Download authorization, vendor terms, actual disk headroom and installation are separate gates.

No private source, credentials, recovered firmware, vendor reference materials, private failure corpora, proprietary containers or nonpublic traces are allowed in this repository. This public workcell provides evidence only. Missing Quartus and positive static checks never imply Quartus or HIL PASS. The minimal pilot is **not** a fully constrained pin-qualified FPGA design.
