# Public fork operations

This repository provides a public-safe execution surface for GitHub repository operations that benefit from GitHub-hosted runners.

## Stable entry point

Use `scripts/github/Repair-UpstreamForks.ps1`.

The stable entry point delegates to the byte-validated implementation in `candidates/Repair-UpstreamForks.ps1`. Keeping the candidate preserves the exact provenance object that was exercised on GitHub-hosted Windows, Ubuntu, and macOS runners while giving humans and workflows a durable operator path.

### Read-only audit

```powershell
pwsh ./scripts/github/Repair-UpstreamForks.ps1 -AuditOnly
```

This verifies configured fork ancestry/default-branch expectations, reports Issues state, and checks common upstream contribution-policy paths. It does not mutate repositories.

### Preview a mutation

```powershell
pwsh ./scripts/github/Repair-UpstreamForks.ps1 -CreateCiIssues -WhatIf
```

Mutation mode requires both `GH_TOKEN` for public reads and a separate `GH_MUTATION_TOKEN` for bounded writes. The script fails closed if mutation authority is missing.

## GitHub Actions

`Public-safe validation` parses all public PowerShell tooling on Windows, Ubuntu, and macOS and runs the stable fork helper in audit-only mode.

`Public fork maintenance` is manual-only. Audit mode is immediately usable with the repository-scoped read-only `GITHUB_TOKEN`. Apply mode additionally requires the protected `public-ops-write` environment and a narrowly scoped GitHub App installation token.

The initial mutation targets are:

- `SupraCraft/VanillaCord`
- `SupraCraft/Bridge`
- `SemperSupra/OpenXcom`

Apply must originate from `main`, requires the exact confirmation phrase `APPLY-PUBLIC-FORK-MAINTENANCE`, runs the audit first, and mints separate short-lived App tokens for the SupraCraft and SemperSupra repository subsets.

## Authority boundary

Do not add private-repository credentials, broad personal access tokens, private source, private fixtures, evaluator data, or restricted engineering knowledge to this public repository merely to gain runner capacity. Public execution produces evidence; it does not confer private promotion authority.
