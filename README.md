# github-ops-lab

Public-safe GitHub Actions execution laboratory for repository-operations tooling.

## Purpose

This repository provides disposable, reproducible GitHub-hosted execution for tooling that can be evaluated entirely with public inputs and public-safe outputs. It is an execution and validation surface, not an authority for private engineering data or promotion decisions.

## Hard boundary

Allowed here:

- public repository metadata and source;
- public-safe PowerShell and `gh` tooling;
- syntax, parser, unit, smoke, and compatibility validation;
- synthetic/public fixtures;
- sanitized logs, hashes, and test evidence.

Not allowed here:

- credentials that can read private repositories;
- private source, corpora, evaluator logic, failure knowledge, or internal prompts;
- organization-wide or broadly scoped mutation credentials;
- secrets copied from private environments;
- treating a successful public workflow as approval to promote or publish elsewhere.

## Execution posture

Pull-request and push validation is non-mutating and uses minimal `GITHUB_TOKEN` permissions. Any future workflow capable of modifying another public repository must be separately designed, manually dispatched, narrowly scoped, and reviewed before it is enabled.

Stable reusable tooling should graduate to its durable public home rather than turning this lab into a product repository.

## Reusable public-site release readiness

`.github/workflows/public-site-readiness.yml` extracts the common public-web CI mechanics proven by the SupraCraft VanillaCord and Bridge pilots. Consumers keep their own candidate generator, deterministic checks, Playwright routes/journeys, theme assertions, Lighthouse routes/budgets, and Lychee paths; the reusable workflow supplies the shared pinned execution mechanics and evidence upload.

A synthetic consumer in `tests/fixtures/public-site-readiness/` exercises the reusable workflow through `.github/workflows/public-site-readiness-selftest.yml`.

See [`docs/public-site-release-readiness.md`](docs/public-site-release-readiness.md) for the consumer contract, base-path containment requirement, accessibility boundary, and pinned-use example.

## GitHub Pages source configuration

`scripts/github/Set-GitHubPagesWorkflow.ps1` idempotently configures one explicitly named **public** repository so **Settings > Pages > Source** uses **GitHub Actions**. It does not create or alter the target repository's Pages deployment workflow.

Read-only audit:

```powershell
./scripts/github/Set-GitHubPagesWorkflow.ps1 SupraCraft/VanillaCord -AuditOnly
```

Preview:

```powershell
./scripts/github/Set-GitHubPagesWorkflow.ps1 SupraCraft/VanillaCord -WhatIf
```

Apply:

```powershell
$env:GH_MUTATION_TOKEN = '<narrowly scoped token>'
./scripts/github/Set-GitHubPagesWorkflow.ps1 SupraCraft/VanillaCord
```

The mutation token must be authorized for the target repository with GitHub Pages and repository Administration write permissions. Keep it repository-scoped rather than organization-wide. Reads may continue to use the ordinary `gh` authentication or `GH_TOKEN`; the helper temporarily uses `GH_MUTATION_TOKEN` only for the mutation and then restores the read token.

The helper refuses private and archived repositories, supports `-WhatIf`, treats an already-correct `build_type=workflow` configuration as a no-op, and re-reads the Pages settings after mutation to fail closed if the requested state was not applied.
