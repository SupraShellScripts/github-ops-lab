# Public validation adoption candidates

## Scope

This survey asks where the lab's proven validation capabilities are likely to reduce real engineering risk or local-agent work across active public repositories. It intentionally does not recommend blanket rollout.

The ranking considers:

- active public repository rather than private/archived state;
- amount and sensitivity of custom GitHub Actions surface;
- build/release/package responsibilities;
- PowerShell content that benefits from real WinPS 5.1 / PowerShell 7 evidence;
- dependency-manifest churn where dependency review can add value;
- fork status and upstream-divergence cost;
- whether a CI modernization issue already exists and can absorb the work without issue sprawl.

## Tier 1 — immediate pilots

### `SemperSupra/windows-package-foundry`

**Payoff: very high.** It currently has three custom workflows, including release-trust and WinInspect lifecycle/readiness workflows, plus repository-local `actions/`, `scripts/`, and `tests/` surfaces.

Recommended composition:

- zizmor on workflow/action changes and default-branch scheduled scans;
- OpenSSF Scorecard on push/schedule;
- existing github-ops-lab WinPS 5.1 / PowerShell 7 validation for PowerShell source;
- dependency review only if/when a supported dependency graph has meaningful dependency manifests;
- later artifact attestation/SBOM work belongs in the Foundry release design rather than this generic lab.

Track through existing `SemperSupra/windows-package-foundry#15`; do not create a duplicate adoption issue.

### `SemperSupra/WinInspect`

**Payoff: very high.** The public repo currently has projected-source CI plus a substantial release workflow. Release automation has higher consequence than ordinary test-only CI, so workflow security scanning has a favorable signal-to-noise ratio.

Recommended composition:

- zizmor immediately;
- Scorecard push/schedule posture evidence;
- PowerShell compatibility where projected public PowerShell is part of the release surface;
- dependency review where supported;
- retain deeper release/provenance/SBOM work under the existing Foundry/governance model.

Track through existing `SemperSupra/WinInspect#11`.

### `SemperSupra/truenas-app-foundry`

**Payoff: very high.** It currently carries five custom workflows spanning appliance build, qualification, base validation, materialization validation, and source-contract validation. This is exactly the kind of workflow-heavy build system where an independent workflow-security validator is useful.

Recommended composition:

- zizmor immediately;
- Scorecard push/schedule;
- dependency review when a supported dependency graph is present;
- keep TrueNAS-specific lifecycle and artifact validation in the project/Foundry rather than centralizing it here.

Track through existing `SemperSupra/truenas-app-foundry#21`.

## Tier 2 — high-confidence follow-ons after the three pilots

### `SemperSupra/garm-provider-truenas`

One substantial CI workflow and a Go/upstream-compatibility surface make zizmor + Scorecard low-cost. Dependency review is useful if the Go module graph is enabled. Track through existing `#18`.

### `SupraShellScripts/userscripts`

A public artifact-verification workflow exists. Zizmor is cheap and dependency review becomes useful as the Node/toolchain surface expands. Track through existing `#5`.

### `SemperSupra/DE2-115`

Hardware/HDL work has expensive feedback loops, so public workflow posture checks are useful where GitHub Actions can catch issues before hardware/local-tool execution. Adopt zizmor/Scorecard as lightweight outer checks; do not pretend they replace FPGA/toolchain validation. Track through existing `#66`.

### `SemperSupra/AgentKVM2USB`

Similar rationale to DE2-115: inexpensive workflow/security evidence can protect the public build/test surface while hardware-specific correctness remains elsewhere. Track through existing `#37`.

### `SemperSupra/SupraBlueSniffer`

Public build/API/synthetic-test work is already planned. Add the lightweight repository/workflow checks as part of existing `#1`, not as a separate program.

## Tier 3 — adopt when their CI surface matures

`SemperSupra/BrowserParity`, `SupraShellScripts/violentmonkey-workbench`, `mark-e-deyoung/secure-messaging`, `SemperSupra/oxce-mod-studio`, `SemperSupra/scrutari`, `SemperSupra/supragoflow`, and `SemperSupra/EvoForge` already have CI-oriented work items, but some currently have little or no public workflow surface. Add the baseline as those CI implementations become real rather than creating empty security workflows in advance.

## Special case — `SupraShellScripts/violentmonkey`

The fork already carries multiple upstream-derived CI, release, store-download, and translation workflows, so zizmor could find meaningful workflow issues. However this is an upstream-oriented maintained fork. Do not inject generic downstream CI merely because it is available. First distinguish inherited upstream findings from fork-introduced findings and keep any fork-only workflow changes narrowly justified.

Dependency review may be useful for the Node dependency graph. Scorecard is not an adoption candidate while the repository remains a fork because the Scorecard action does not support fork repositories.

## Forks: audit, do not standardize blindly

`SupraCraft/VanillaCord`, `SupraCraft/Bridge`, and `SemperSupra/OpenXcom` should not receive the same blanket stack as independent repositories. Scorecard is not supported for fork repositories. Zizmor is useful only where a meaningful workflow surface exists and should be used first as an audit, with upstream-vs-fork differences classified before changing the fork.

Their existing fork-maintenance/CI work items remain the coordination surface.

## No-current-payoff / defer

Do not add validation plumbing merely to make a repository look standardized when there is little for it to validate. Defer empty or near-empty public projections such as `SemperSupra/playnite-auto-report`, `SemperSupra/mcp-projection`, `SupraShellScripts/stateless-dev-tooling`, and similarly thin deployment shells until their public execution surface exists.

Simple static sites and legacy/archived repositories are also outside the initial rollout unless they resume active development.

## Dependency review rule

Dependency review is a **consumer-repository capability**, not a universal github-ops-lab broker. GitHub requires the dependency graph to be enabled. The lab self-test demonstrated that an otherwise-valid public repository can have that prerequisite disabled, in which case the action correctly refuses to run.

For active Node, Go, Maven/Gradle, Python, or other supported ecosystems with meaningful PR dependency changes, enable the graph and adopt the dependency-review action directly in that repository. Do not hide an unsupported configuration behind `continue-on-error`.

## Pilot success criteria

Run the Tier-1 pilots before broader adoption. Continue rollout only if the evidence shows at least one of:

- real workflow/security defect found;
- release/build risk reduced;
- local/manual review eliminated or materially shortened;
- reusable configuration with little project-specific code.

If the checks mostly generate accepted noise or require repeated project-specific suppression, stop the rollout and keep the lab as an on-demand audit surface instead.
