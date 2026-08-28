# Public validation strategy

## Purpose

`github-ops-lab` is a public proving ground and execution substrate for deterministic validation that benefits from GitHub-hosted runners. It is not intended to become a bespoke CI/security platform or a central source of broad portfolio authority.

## Decision

Prefer maintained upstream tools over custom implementations. Add custom code only when a demonstrated portfolio requirement is not adequately covered by maintained public tooling.

The near-term baseline is:

- PowerShell compatibility: the existing real Windows PowerShell 5.1 / PowerShell 7 validator;
- GitHub Actions/workflow security: `zizmor`;
- repository security posture: OpenSSF Scorecard;
- pull-request dependency risk: GitHub `dependency-review-action`, adopted directly in consumer repositories where GitHub Dependency Graph is enabled;
- portfolio-specific fork/repository topology: the existing bounded `gh` helper.

`actionlint` remains a candidate only if experiment evidence shows useful findings not already covered by GitHub workflow parsing and zizmor.

The lab does not wrap every upstream validator merely for centralization. The first dependency-review self-test proved that this repository currently has Dependency Graph disabled; GitHub's action correctly fails as unsupported in that state. Rather than weaken failure semantics with `continue-on-error`, dependency review stays a direct consumer capability and is enabled only where its prerequisite is present.

## Authority boundary

Public validation produces evidence. It does not grant private promotion, merge, release, deployment, or cross-repository mutation authority.

Default validation:

- uses public inputs only;
- uses least-privilege `GITHUB_TOKEN` permissions;
- pins third-party Actions to immutable commit SHAs;
- pins tool versions where an Action otherwise selects a floating tool release;
- does not receive credentials that can read private repositories;
- does not execute arbitrary target project code merely to inspect it;
- does not convert absence of findings into a proof of safety.

Any cross-repository mutation remains a separately designed, manual, bounded, protected operation. When GitHub App tokens are required, both repository selection and requested installation-token permissions are explicitly narrowed.

## Explicit non-goals for this phase

Do not build or import, merely because it is technically possible:

- a custom general GitHub Actions security scanner;
- a bespoke SLSA/provenance implementation when GitHub-native attestations suffice;
- a generalized clean-room execution framework;
- a central multi-project orchestration platform;
- a private-to-public projection exporter;
- broad personal/org mutation credentials;
- a duplicate SBOM ecosystem where maintained standard tools can be integrated instead.

## Experiment and stop rule

Adopt the baseline against representative public repositories and measure:

1. meaningful defects found;
2. local-agent or local-workstation work avoided;
3. reuse with little project-specific customization;
4. maintenance burden compared with benefit.

If the stack mostly produces noise, duplicates existing CI, or becomes expensive to maintain, stop generalizing it.

## Graduation rule

The lab is the place to experiment, qualify, compare, and collect evidence. A capability that becomes stable and broadly consumed should graduate to a durable shared public tooling home rather than turning this repository into an increasingly critical monolith.

## Evidence semantics

Different checks establish different claims:

- parser/runtime compatibility establishes compatibility evidence, not behavioral equivalence;
- static workflow/security findings identify risk patterns, not exploitability;
- Scorecard reports repository/supply-chain posture, not overall correctness;
- dependency review evaluates dependency deltas, not the whole dependency graph in isolation;
- SBOM/provenance/attestation establishes identity and origin relationships, not artifact safety.

Consumers and private governance decide how those evidence products affect promotion or release decisions.
