# PowerShell compatibility validation

`github-ops-lab` provides a public-safe validation service for PowerShell-heavy public repositories.

## Evidence levels

1. **Parse compatible** — the same source bytes are accepted by the real Windows PowerShell 5.1 parser and the real PowerShell 7 parser on GitHub-hosted Windows. Additional PS7 Linux/macOS lanes show portable parser acceptance.
2. **Static risk reviewed** — the scanner records bounded heuristic findings for dynamic or high-impact commands. This is review assistance, not proof of safety. Absence of findings is not a safety guarantee.
3. **Test equivalent** — reserved for a later opt-in lane where the project declares a deterministic test harness and the same tests pass under both required runtimes. Parsing alone must never be labeled behavioral equivalence.

The default workflow does **not execute target scripts**.

## Manual use

Open Actions -> **PowerShell compatibility** -> **Run workflow** and provide:

- public `owner/repo`;
- branch, tag, or commit SHA;
- relative path to scan, normally `.`.

The workflow checks out the public target read-only and scans `.ps1`, `.psm1`, and `.psd1` files in four lanes:

- real Windows PowerShell 5.1 on `windows-latest`;
- PowerShell 7.x on Windows;
- PowerShell 7.x on Ubuntu;
- PowerShell 7.x on macOS.

Each lane emits JSON containing runtime identity, source hashes, parser diagnostics, and heuristic findings. A comparison job verifies that the Windows 5.1 and Windows PS7 lanes examined the same bytes and reports cross-engine incompatibilities.

## Reusable workflow

A public repository can call:

```yaml
jobs:
  powershell-compat:
    uses: SupraShellScripts/github-ops-lab/.github/workflows/powershell-compatibility.yml@main
    with:
      path: .
```

When called from another repository, an empty `repository` input means the caller repository and an empty `ref` means the caller SHA. The caller can also supply an explicit public repository/ref.

## Local scanner

The scanner itself remains usable locally when the relevant engine exists:

```powershell
powershell.exe -NoProfile -File ./scripts/powershell/Test-PowerShellCompatibility.ps1 -Root . -OutputPath ./winps51.json -Lane winps51-windows
pwsh -NoProfile -File ./scripts/powershell/Test-PowerShellCompatibility.ps1 -Root . -OutputPath ./ps7.json -Lane ps7-windows
pwsh -NoProfile -File ./scripts/powershell/Compare-PowerShellCompatibility.ps1 -ResultsRoot . -OutputPath ./comparison.json -RequireWinPS51AndPS7
```

The public service exists specifically so projects do not need to reproduce Windows PowerShell 5.1 locally merely to obtain parser compatibility evidence.

## Boundaries

- public repositories only;
- read-only target checkout;
- no target script execution in default mode;
- no private credentials or private source;
- parser compatibility is not behavioral equivalence;
- heuristic risk findings are not a safety proof;
- Windows PowerShell 5.1 evidence comes from actual `powershell.exe` 5.1, never inferred from PS7 or a Linux container.
