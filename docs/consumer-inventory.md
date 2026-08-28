# Derived consumer inventory

`github-ops-lab` does not maintain an authoritative registry of consumer repositories.

The authoritative statement of what a repository runs is the consumer repository itself, especially its `.github/workflows` files. This lab only derives an observation of those public relationships so humans and automation can answer portfolio-level questions without duplicating configuration.

## Authority

The generated inventory is explicitly labeled `derived-non-authoritative`.

If the generated report disagrees with a consumer repository, the consumer repository wins and the inventory should be regenerated or the scanner corrected. Adding, removing, or changing a consumer workflow must not require a synchronized change in this repository.

## What is observed

The scanner discovers public repositories for the bounded owner set and reads workflow YAML as text. It records literal `uses:` references, including:

- repository and workflow path;
- action or reusable-workflow reference;
- known capability classification;
- whether the reference is pinned to a full 40-character Git commit SHA;
- whether the relationship is directly observed or ambiguous.

Known capabilities currently include zizmor, OpenSSF Scorecard, GitHub dependency review, the lab PowerShell compatibility workflow, and the public fork-maintenance workflow.

The scanner also reports other action/reusable-workflow references because pinning posture is useful portfolio evidence even when the action is not one of the lab's named capabilities.

## Conservative semantics

A dynamic or expression-bearing `uses:` value is recorded as `ambiguous-not-asserted`. The scanner does not claim it has resolved a relationship it cannot determine from repository text.

This is intentionally not a full YAML evaluator. It is a deterministic observer for the workflow forms GitHub accepts for action and reusable-workflow references. If future workflow syntax cannot be interpreted safely, the scanner should expose uncertainty rather than guess.

## Outputs

The workflow produces:

- `public-validation-consumers.json` — canonical machine-readable observation;
- `public-validation-consumers.md` — concise human report and job summary.

The generated files are workflow artifacts, not hand-edited repository state. Regenerate them from current public repositories when a fresh portfolio view is needed.

## Exceptions and intent

Do not create a central consumer list just to document facts already visible in workflows.

A future exceptions/intent file is justified only for facts that cannot be inferred, such as an explicit decision not to use a capability because a repository is an upstream fork. Such a file should remain small and must not duplicate detected workflow configuration.
