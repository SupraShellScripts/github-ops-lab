# GitHub topology migration discovery

Issue: #36  
Governance authority: `[REDACTED]#66`

## Purpose

This document defines the public-safe tooling contract for the **Discover** phase of repository-topology migration. It does not define desired topology and does not authorize mutation.

The portfolio process is:

```text
Discover -> Plan -> Apply -> Verify
```

`github-ops-lab` owns reusable public-safe mechanics. Private inventory, migration decisions, access data, and authoritative desired state remain outside this public repository.

## Collector strategy

Use existing GitHub migration/audit tooling before writing custom collectors.

### Primary candidates

| Tool | Intended role | Initial assessment |
|---|---|---|
| `[REDACTED]` | rich organization/repository inventory | strongest primary candidate; resumable JSON, dry-run estimates, Actions, Pages, packages, webhooks, custom properties |
| `[REDACTED]` | migration inventory baseline | simpler and GitHub-documented; useful comparison/control collector |
| `[REDACTED]` | dependency-edge discovery | promising for repository dependencies; requires empirical coverage test |
| `gh api` / GraphQL / code search | gap filler | required for personal namespace, literal references, governance-specific semantics, and unsupported fields |
| `gh-pma` / `gh-migration-validator` | later Verify evaluation | evaluate only after determining whether their migration assumptions match GitHub-to-GitHub transfer/rename operations |

No tool is authoritative. Raw collector output is evidence. Governance defines desired state.

## Normalized discovery contract

A normalized repository record SHOULD be representable as JSON/YAML with the following logical groups. Missing data must be explicit rather than inferred.

```yaml
schema: supra/github-topology-discovery/v1
collector:
  name: gh-stats
  version: unknown
  collected_at: 2026-08-30T00:00:00Z
  source_file: raw/...
repository:
  owner: example
  name: repo
  full_name: example/repo
  visibility: public
  archived: false
  fork: false
  upstream: null
  default_branch: main
  created_at: null
  updated_at: null
  pushed_at: null
features:
  issues: unknown
  pull_requests: unknown
  discussions: unknown
  wiki: unknown
  projects: unknown
  pages: unknown
  packages: unknown
  releases: unknown
actions:
  workflow_count: null
  reusable_workflow_dependencies: []
  action_dependencies: []
protection:
  branch_protection_summary: unknown
  ruleset_summary: unknown
private_sensitive:
  collaborator_summary: omitted
  team_summary: omitted
  webhook_summary: omitted
  deploy_key_summary: omitted
references:
  current_identity_hits: []
  candidate_old_identity_hits: []
migration_risk:
  flags: []
  unknowns: []
governance_hints:
  authority_role: unknown
  sibling_relationship: unknown
  intended_destination: unknown
```

The `private_sensitive` block MUST NOT be emitted to a public artifact when populated with private fleet information.

## Discovery invariants

1. Discovery is read-only.
2. Raw output is retained separately from normalized output.
3. Every normalized field retains collector provenance or is marked unknown.
4. A missing API field is not equivalent to `false` or `none`.
5. Public CI uses only public/synthetic inputs.
6. Broad private-read or organization-admin credentials are never stored in this public repository.
7. Unsanitized discovery output is never uploaded as a public Actions artifact.
8. Cross-repository references are classified as **authoritative/current**, **historical/provenance**, or **unresolved**; they are not blindly rewritten.
9. Tool selection is evidence-driven: coverage, permissions, API cost, reproducibility, output stability, and maintenance burden are measured.

## Evaluation matrix

For each candidate collector record:

- installation/version reproducibility;
- supported GitHub account type (organization, personal namespace, repository list);
- token/scopes required;
- dry-run/read-only guarantees;
- rate-limit/API-call estimate support;
- resume/retry behavior;
- JSON/CSV schema stability;
- repository metadata coverage;
- Actions/workflow dependency coverage;
- Pages/package/webhook coverage;
- collaborators/team/access coverage;
- cross-repository reference coverage;
- private-data exposure risk;
- suitability for before/after snapshots;
- gaps requiring `gh api` or custom logic.

## Pilot order

1. Install/probe candidate extensions and capture versions/help output.
2. Execute public-only tests against explicitly named public repositories/organizations.
3. Validate raw-output parsing and normalized schema with synthetic fixtures.
4. Run private authenticated discovery only from an approved private/local execution plane.
5. Compare collectors against the contract above.
6. Select the smallest viable collector set.
7. Expand discovery in bounded namespaces/orgs.

## Expected architecture

```text
existing collectors
    |-- gh-stats
    |-- gh-repo-stats
    |-- gh-repo-map
    `-- gh api/search gap fillers
             |
             v
       raw immutable snapshots
             |
             v
        normalization
             |
             v
 private governance migration ledger / plan
```

This repository should not evolve into a second topology database. Its durable product is the reproducible tooling and schema contract, not the live fleet state.
