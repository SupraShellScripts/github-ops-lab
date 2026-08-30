# GitHub topology migration discovery

## Purpose

This document defines a generic, public-safe tooling contract for the **Discover** phase of repository-topology migration. It does not define any particular portfolio's desired topology and does not authorize mutation.

The process is:

```text
Discover -> Plan -> Apply -> Verify
```

This repository owns only reusable public-safe mechanics. Private inventory, access data, migration decisions, and authoritative desired state belong in the operator's private control plane.

## Collector strategy

Prefer existing GitHub migration/audit tooling before writing custom collectors. Candidate tools include `mona-actions/gh-stats`, `mona-actions/gh-repo-stats`, `mona-actions/gh-repo-map`, and targeted GitHub API/GraphQL/search queries. No collector is authoritative; raw output is evidence and the operator's governance defines desired state.

## Public-safe normalized contract

A generic normalized repository record may contain public-safe fields such as repository identity, visibility, archived/fork/default-branch state, timestamps, public feature flags, workflow dependency summaries, protection summaries, reference classifications, migration-risk flags, and collector provenance.

Private access data such as collaborator/team inventories, webhook configuration, deploy-key data, private repository relationships, and estate-specific authority/priority semantics must not be emitted into public artifacts.

## Discovery invariants

1. Discovery is read-only.
2. Raw output is retained separately from normalized output.
3. Every normalized field retains collector provenance or is explicitly unknown.
4. Missing data is not equivalent to `false` or `none`.
5. Public CI uses only public or synthetic inputs.
6. Broad private-read/admin credentials are never stored in this public repository.
7. Unsanitized private discovery output is never uploaded as a public artifact.
8. Cross-repository references are classified before rewrite; historical provenance is not blindly changed.
9. Tool selection is evidence-driven: coverage, permissions, API cost, reproducibility, output stability, and maintenance burden are measured.

## Evaluation matrix

For each candidate collector, evaluate installation/version reproducibility, supported account types, required permissions, dry-run/read-only guarantees, API/rate-limit behavior, resume/retry behavior, schema stability, metadata/dependency/protection coverage, private-data exposure risk, before/after suitability, and gaps requiring targeted API logic.

## Pilot order

1. Probe install/help/output contracts without private data.
2. Run public-only tests against explicitly public inputs.
3. Validate parsing/normalization with synthetic fixtures.
4. Run private authenticated discovery only from an approved private/local execution plane.
5. Compare collector coverage against the private operator's requirements.
6. Select the smallest viable collector set.
7. Expand in bounded scopes.

## Public/private boundary

This repository must not become a live topology database or portfolio strategy repository. Its durable public product is reusable mechanics, schemas, and public-safe tests. Estate-specific orchestration, inventories, priorities, private relationships, migration plans, and raw private evidence remain outside this repository.
