# PSGitLite P0 — public-original consolidation and promotion boundaries

## Scope
This branch contains only publicly authored synthetic Git-compatible PowerShell modules, test fixtures and one integrated CI workflow. It is a reproducible public qualification laboratory and **not** an operational AIrea51 deployment, a privileged DoD tool, or a general Git CLI drop-in.

## Provenance and executed evidence
Assembled without introducing or modifying private source, secrets, real endpoints or private-runner dependencies. Canonical source modules and v2 package test reuse byte-identical Git blobs from public `work/psgitlite-v2-package-20261103`; the object-symlink, after-ref process-kill and v2 competing-writer tests reuse qualified public Git blobs from their owning work branches.

Prior native $0 standard public runner receipts:
- v1 and deep-history baseline: Actions 41632693206.
- v2 effect assessor: Actions 41662350368.
- redirected-object negatives: Actions 41662668524.
- v2 Git writer and v1 compatibility: Actions 41663245310.
- safe Human/JSON/JSONL inspect: Actions 41664001271.
- post-ref hard process kill: Actions 41664299318.
- v2 independent writer CAS: Actions 41665240460.
- six-file SHA256-manifested v2 cleanroom source-only distribution: Actions 41665620199.

The consolidated integrated workflow `.github/workflows/psgitlite-p0-integration.yml` must pass Windows PowerShell 5.1 and Linux pwsh **at this branch's exact source HEAD** before approval to merge to the public lab's protected `main`. Initial individual branch passes do not prove combined composition until the integrated suite completes.

## Intentional holds
No private GitHub-hosted Actions minutes, no private source exposure, no production credentials or model API keys, no network Git remote, no access to restricted workstations, no bypass of CLM/JEA/WDAC, no merge into private AIrea51, and no release or deployment. Full Git compatibility, migration of live v1 DLE histories, crash-consistent directory fsync, and private native G1/runtime admission remain future governed workcells.

Worktrees on external machines cannot be inspected from GitHub API; GitHub branch and PR snapshots are not evidence of local worktree cleanliness or actor ownership. Keep corresponding owner DLE and test evidence referenced by exact commit SHA.
