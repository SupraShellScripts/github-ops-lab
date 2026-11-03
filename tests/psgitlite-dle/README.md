# PSGitLite DLE: public-original offline checkpoint prototype

This is an independently qualified, public-synthetic donor for AIrea51's future pure-PowerShell local Durable, Legible, Executable (DLE) engine. It is NOT a production AIrea51 module, work-host deployment approval, or a general-purpose Git replacement. The existing Git-less signed source-capsule bootstrap remains independently mandatory for restricted hosts.

## Objectives

- P0: offline local DLE checkpoints, trustworthy intent/observation/verification distinction, crash/restart recovery and exact next baton.
- P1: later extend the SAME canonical Git-compatible object model to full Git-like CLI, clone, fetch, pull, push, advanced workflows and remote protocols. None of those network commands are implemented here.
- Runtime: Windows PowerShell 5.1 or PowerShell 7 with built-in .NET, no Git executable, native dependency, COM, Add-Type, admin, Python, Node, external process or network.

## Data and storage contract

Initialize a disposable isolated Git SHA-1 repository with main HEAD. DLE checkpoints use one independent Git ref per workset, in the namespace refs/airea51/dle/<workset>. Each real Git commit contains three Git blobs in a canonical tree:

- event.json: immutable event, including worksetId, requestId, requestDigest, stepId, DOPAV phase, status, intended and observed effects, evidenceRefs, actor, sourceRootDigest, approvalRef, parentCommit, createdUtc, nextBaton.
- checkpoint.json: versioned summary, previousCommit, request and state identities.
- baton.md: human-legible next action.

Status vocabulary: INTENT, OBSERVED, VERIFIED, FAILED, UNKNOWN. A fresh session reading INTENT, OBSERVED or UNKNOWN reports RECONCILE_REQUIRED. No automatic external action occurs in the module. An approvalRef is an untrusted *reference*, not a verified signature, approval grant, or proof of source authority.

New checkpoints write Git objects, verify their hashes, acquire a per-ref CreateNew .lock, check the exact expected HEAD under that lock, flush the new ref contents and move/replace atomically. No blind lock cleanup on next run. Retry of exactly the most recent requestId and matching requestDigest is idempotent. Stale distinct writers and reused historical request IDs fail closed.

## Test and build files

- PSGitLiteDle.psm1 -- local Git checkpoint, CAS ref, history and snapshot API.
- Invoke-GitLiteDle.ps1 -- Human, Json and Jsonl commands (Init, Checkpoint, Inspect, History).
- Test-Dle.ps1 -- positive, negative, restart, immutable-history and independent native Git fsck tests.
- Test-DleCli.ps1 -- three-audience interface and approval/source reference custody.
- Test-DleCrash.ps1 -- actual hard termination inside a test-only instrumented copy of writer, immediately before CAS, then cold readback and explicit lock recovery.
- Test-DleConcurrency.ps1 -- two separate PowerShell writer processes race on the same old head; exactly one must win.
- Test-DlePackage.ps1 -- SHA256-hashed deterministic source-only distribution and clean-room no-Git smoke test.
- Existing sibling psgitlite-native/PSGitLiteCore.psm1 -- independently qualified pure PowerShell Git object donor.
- .github/workflows/psgitlite-dle-cloud.yml -- public $0 Windows PowerShell 5.1 and Linux pwsh native qualification in short jobs.

## Sample API

The product facade is a PowerShell script, not a replacement native git.exe:

~~~powershell
$cli = '.\tests\psgitlite-dle\Invoke-GitLiteDle.ps1'
& $cli -Command Init -RepositoryPath .\dle-repo -OutputFormat Human
& $cli -Command Checkpoint -RepositoryPath .\dle-repo -WorksetId sample -RequestId task0001 -StepId observation -Phase Observe -Status INTENT -Message 'Synthetic only' -NextBaton 'Reconcile effect' -ExpectedHead '' -OutputFormat Json
& $cli -Command Inspect -RepositoryPath .\dle-repo -WorksetId sample -OutputFormat Human
& $cli -Command History -RepositoryPath .\dle-repo -WorksetId sample -OutputFormat Jsonl
~~~

Subsequent writes must use the exact previous Head in ExpectedHead; do not overwrite any shared history silently.

## Validated and not-yet-validated boundaries

The exact public original source is qualified only if the corresponding Windows/Linux GHA job passed at its exact commit. Independent native Git is a test oracle ONLY, never part of the product. Hard process termination after flushed lock is tested; physical disk power failure, directory fsync, network filesystems, CLM/JEA/WDAC, real workstations and cryptographic authorization are NOT tested. Nor are arbitrary existing repositories, SHA-256 DLE commits, packed-only DLE history, reftable, linked worktrees, multi-ref transactions, large repositories, long-term compaction, or Git remote push/pull.

Current write history scans are capped at 128 commits; fail closed on longer chains pending checkpoint compaction/migration. The module does not run model-generated programs or execute DLE actions by itself; it stores their declared and observed outcomes.

Project authority lives in private AIrea51 #23, under #22, with active AIrea51 LINT-009/#13/PR #15 and PSTriage #49 boundaries unchanged. Only synthetic public-source files belong in this public test lab. No private GitHub Actions minutes, real restricted evidence, secrets, private code, merge, release or deployment.

## Promotion sequence

1. Reconcile the existing private AIrea51 exact source/head and G1 suite. Qualify private native tests on an authorized actor, not by publishing private code.
2. Independently review and hash-pin this public donor and its tests in a new isolated private worktree/branch, without modifying the active handoff.
3. Extend test coverage for security on untrusted repository paths, Windows case collisions, resource bounds, OID formats, multi-process races and varied filesystem faults.
4. Integrate the verified read-only + checkpoint backend with AIrea51's existing dispatcher and durable handoff format only under separate owner acceptance.
5. Admit capabilities on real host after OS language mode, filesystem, code-loading, credential, egress and signer policy checks. Preserve the Git-less signed-capsule path when the Git engine is not admitted.


## Optional AIrea51 handoff observer (synthetic-tested)

Invoke-DleHandoffObserve.ps1 is an additive input adapter, not an alternate authority. Given a locally admitted AIrea51 ProjectRoot and an isolated DLE RepositoryPath, it hashes the existing agent-exchange/current.json bytes, validates its version, repository identity and relative prompt/report path scope, and records an OBSERVED event with only the hash and minimal AGENTS.md cold-start instruction. It **never rewrites current.json**, reads no private source files named by that pointer, and does not declare approval/verified external effects. A stable digest produces an idempotent request ID; a changed handoff produces a distinct event under expected-head CAS.

Test-DleHandoff.ps1 uses a public synthetic current.json containing a sentinel next action, proves sentinel text stays out of the DLE/event output, verifies exact SHA256 linkage and idempotency, rejects a traversal promptPath, records a changed pointer as a new Git commit, and checks independent native Git fsck.

The observer is included in the source-only distribution. Its passing synthetic tests do NOT admit real private AIrea51 handoff integration or restricted-host deployment. No owner/current handoff changes result from this workcell.
