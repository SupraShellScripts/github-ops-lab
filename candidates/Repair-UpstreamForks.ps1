#requires -Version 7.0
<#
.SYNOPSIS
  Audit and repair the GitHub settings for the SupraCraft/SemperSupra upstream-oriented forks.

.DESCRIPTION
  - Verifies each repository is still a fork of the expected immediate upstream.
  - Enables fork-local GitHub Issues.
  - Reports fork/upstream default branches and selected repository settings.
  - Searches common upstream contribution-policy locations for explicit AI/LLM policy text.
  - Does NOT infer that silence means AI contributions are accepted.
  - Does NOT change upstream repositories.
  - Does NOT alter source, branches, merge history, or private/public boundaries.

  Engineering-governance intent:
    * Fork-local Issues are coordination/work tracking.
    * Upstream-facing changes should follow upstream conventions.
    * AI-written/AI-assisted changes are not proposed upstream until upstream acceptance
      is explicit or a maintainer has confirmed the policy.
#>

[CmdletBinding(SupportsShouldProcess)]
param(
    [switch]$AuditOnly,
    [switch]$CreateCiIssues
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

function Invoke-GhJson {
    param(
        [Parameter(Mandatory)][string[]]$Args
    )
    $raw = & gh @Args 2>&1
    if ($LASTEXITCODE -ne 0) {
        throw "gh $($Args -join ' ') failed:`n$raw"
    }
    if (-not $raw) { return $null }
    return ($raw | Out-String | ConvertFrom-Json)
}

function Test-GhPath {
    param(
        [Parameter(Mandatory)][string]$Repo,
        [Parameter(Mandatory)][string]$Path
    )
    & gh api "repos/$Repo/contents/$Path" --silent 2>$null
    return ($LASTEXITCODE -eq 0)
}

function Get-GhTextFile {
    param(
        [Parameter(Mandatory)][string]$Repo,
        [Parameter(Mandatory)][string]$Path
    )
    $obj = Invoke-GhJson -Args @('api', "repos/$Repo/contents/$Path")
    if ($obj.encoding -ne 'base64') {
        return $null
    }
    $bytes = [Convert]::FromBase64String(($obj.content -replace '\s',''))
    return [Text.Encoding]::UTF8.GetString($bytes)
}

$forks = @(
    [pscustomobject]@{
        Fork = 'SupraCraft/VanillaCord'
        ExpectedParent = 'ME1312/VanillaCord'
        ExpectedDefaultBranch = 'master'
        CiTitle = 'ci: add Minecraft/JDK compatibility matrix and upstream-release checks'
        CiBody = @'
## Objective
Use public GitHub Actions to continuously validate this fork against supported Minecraft and Java versions while keeping changes suitable for upstream contribution.

## Work
- clean Maven build from the exact public SHA;
- supported Java-version matrix;
- ordinary public-safe smoke/unit tests;
- scheduled detection of relevant Minecraft/upstream releases;
- bounded compatibility runs when upstream versions change;
- artifact hashes, SBOM, and provenance where useful;
- immutable/pinned third-party Actions and least-privilege permissions;
- machine-readable compatibility evidence.

## Upstream discipline
This is an upstream-oriented fork. Changes should preserve upstream layout, style, interfaces, and contribution conventions wherever practical. Fork-specific changes should be isolated and justified.

Before proposing AI-written or materially AI-assisted changes upstream, obtain or cite an explicit upstream AI-contribution policy or maintainer approval. Silence is not approval.

## Governance boundary
Public CI uses public-safe inputs only. Do not publish private evaluators, comprehensive compatibility corpora, failure knowledge, credentials, or private-repository data merely to gain public runner capacity.

## Acceptance
- [ ] Clean build runs on supported Java versions.
- [ ] Public-safe compatibility/smoke matrix is explicit.
- [ ] Scheduled upstream/Minecraft change detection is bounded and deterministic.
- [ ] Exact source/toolchain/upstream identities are recorded.
- [ ] Upstream contribution path and AI-acceptance status are documented before upstream PRs.
'@
    }
    [pscustomobject]@{
        Fork = 'SupraCraft/Bridge'
        ExpectedParent = 'ME1312/Bridge'
        ExpectedDefaultBranch = 'master'
        CiTitle = 'ci: add Java compatibility, Maven verification, and upstream-release checks'
        CiBody = @'
## Objective
Use public GitHub Actions to continuously validate Bridge across supported Java/Maven environments while keeping the fork easy to upstream.

## Work
- clean Maven build/verify from exact public SHA;
- supported JDK matrix;
- ordinary public-safe unit/smoke tests;
- bytecode/plugin compatibility checks using public-safe fixtures;
- scheduled detection of relevant Java/Maven/upstream releases;
- hashes, SBOM, and provenance for artifacts where useful;
- immutable/pinned third-party Actions and least-privilege permissions.

## Upstream discipline
This is an upstream-oriented fork. Follow ME1312/Bridge naming, layout, style, Maven conventions, and PR expectations. Prefer narrowly upstreamable changes over fork-only divergence.

Before proposing AI-written or materially AI-assisted changes upstream, obtain or cite an explicit upstream AI-contribution policy or maintainer approval. Silence is not approval.

## Governance boundary
Public CI uses only public-safe inputs and ordinary tests. Specialized evaluator knowledge, private corpora, reverse-engineering findings, credentials, and private-repository data remain outside public CI.

## Acceptance
- [ ] Supported JDK/Maven matrix passes from a clean checkout.
- [ ] Public-safe bytecode/plugin smoke checks are automated.
- [ ] Relevant upstream/runtime changes can trigger bounded checks.
- [ ] Exact source/toolchain/upstream identities are recorded.
- [ ] Upstream contribution path and AI-acceptance status are documented before upstream PRs.
'@
    }
    [pscustomobject]@{
        Fork = 'SemperSupra/OpenXcom'
        ExpectedParent = 'MeridianOXC/OpenXcom'
        ExpectedDefaultBranch = 'oxce-plus'
        CiTitle = 'ci: add reproducible compiler/platform build matrix and public smoke tests'
        CiBody = @'
## Objective
Use public GitHub Actions to validate the oxce-plus fork across supported public build environments without turning the fork into an unnecessarily divergent development line.

## Work
- reproduce the upstream/parent build conventions first;
- clean compiler/platform build matrix where GitHub-hosted runners support it;
- ordinary public-safe smoke/regression subset;
- dependency/toolchain identity recording;
- release artifact hashes, SBOM, and provenance where applicable;
- scheduled parent/upstream change detection with bounded compatibility runs;
- immutable/pinned third-party Actions and least-privilege permissions.

## Upstream discipline
The immediate parent is MeridianOXC/OpenXcom and the wider source lineage is OpenXcom/OpenXcom. Preserve the parent branch/layout/style and determine the appropriate contribution destination for each change before upstreaming it.

Before proposing AI-written or materially AI-assisted changes upstream, obtain or cite an explicit AI-contribution policy or maintainer approval from the intended destination. Silence is not approval.

## Governance boundary
Public CI may contain ordinary public-safe tests only. Do not publish comprehensive evaluator corpora, rare failure knowledge, proprietary game assets, credentials, or private-repository data merely to use public runners.

## Acceptance
- [ ] CI reflects parent/upstream build conventions before adding fork-specific mechanics.
- [ ] Supported public compiler/platform builds run reproducibly.
- [ ] Ordinary public-safe smoke tests are clearly distinguished from comprehensive validation.
- [ ] Exact source/toolchain/parent identities are recorded.
- [ ] Intended upstream destination and AI-acceptance status are documented before upstream PRs.
'@
    }
)

$policyPaths = @(
    'AI_POLICY.md',
    '.github/AI_POLICY.md',
    'AI.md',
    '.github/AI.md',
    'CONTRIBUTING.md',
    '.github/CONTRIBUTING.md',
    'AGENTS.md',
    '.github/copilot-instructions.md'
)

& gh auth status
if ($LASTEXITCODE -ne 0) {
    throw 'GitHub CLI is not authenticated. Run: gh auth login'
}

$results = foreach ($entry in $forks) {
    Write-Host "`n=== $($entry.Fork) ===" -ForegroundColor Cyan

    $repo = Invoke-GhJson -Args @('api', "repos/$($entry.Fork)")
    if (-not $repo.fork) {
        throw "$($entry.Fork) is no longer reported by GitHub as a fork; refusing to mutate."
    }

    $actualParent = [string]$repo.parent.full_name
    if ($actualParent -ne $entry.ExpectedParent) {
        throw "$($entry.Fork) parent is '$actualParent', expected '$($entry.ExpectedParent)'; refusing to mutate."
    }

    if ([string]$repo.default_branch -ne $entry.ExpectedDefaultBranch) {
        Write-Warning "$($entry.Fork) default branch is '$($repo.default_branch)', expected '$($entry.ExpectedDefaultBranch)'. No branch change will be made automatically."
    }

    $upstream = Invoke-GhJson -Args @('api', "repos/$actualParent")

    Write-Host "Fork parent:       $actualParent"
    Write-Host "Fork branch:       $($repo.default_branch)"
    Write-Host "Upstream branch:   $($upstream.default_branch)"
    Write-Host "Fork Issues:       $($repo.has_issues)"
    Write-Host "Upstream Issues:   $($upstream.has_issues)"
    Write-Host "Fork visibility:   $($repo.visibility)"

    if (-not $AuditOnly -and -not $repo.has_issues) {
        if ($PSCmdlet.ShouldProcess($entry.Fork, 'Enable fork-local GitHub Issues')) {
            & gh api --method PATCH "repos/$($entry.Fork)" -F has_issues=true --silent
            if ($LASTEXITCODE -ne 0) {
                throw "Failed to enable Issues for $($entry.Fork)"
            }
            Write-Host 'Enabled fork-local Issues.' -ForegroundColor Green
        }
    }

    # Search only explicit/common policy locations. Absence is UNKNOWN, never "allowed".
    $policyHits = @()
    foreach ($path in $policyPaths) {
        if (Test-GhPath -Repo $actualParent -Path $path) {
            $text = Get-GhTextFile -Repo $actualParent -Path $path
            if ($null -ne $text) {
                $mentionsAI = $text -match '(?i)\b(AI|artificial intelligence|LLM|ChatGPT|Copilot|Claude|generated code)\b'
                $policyHits += [pscustomobject]@{
                    Path = $path
                    MentionsAI = $mentionsAI
                }
            }
        }
    }

    $explicitAi = @($policyHits | Where-Object MentionsAI)
    $aiStatus = if ($explicitAi.Count -gt 0) {
        'EXPLICIT_POLICY_TEXT_FOUND_REVIEW_REQUIRED'
    } else {
        'UNKNOWN_NO_EXPLICIT_REPO_POLICY_FOUND'
    }

    Write-Host "AI upstream status: $aiStatus"
    if ($policyHits.Count -gt 0) {
        Write-Host "Contribution/policy files found:"
        $policyHits | ForEach-Object {
            Write-Host ("  {0}  AI mention={1}" -f $_.Path, $_.MentionsAI)
        }
    } else {
        Write-Host 'No common contribution/AI policy files found in the immediate parent.'
    }

    if ($CreateCiIssues -and -not $AuditOnly) {
        # Idempotence: do not create a second issue with the same title.
        $existing = & gh issue list --repo $entry.Fork --state all --search ('"{0}" in:title' -f $entry.CiTitle) --json number,title --limit 20 | ConvertFrom-Json
        $match = @($existing | Where-Object title -eq $entry.CiTitle)
        if ($match.Count -eq 0) {
            if ($PSCmdlet.ShouldProcess($entry.Fork, "Create CI issue '$($entry.CiTitle)'")) {
                & gh issue create --repo $entry.Fork --title $entry.CiTitle --body $entry.CiBody
                if ($LASTEXITCODE -ne 0) {
                    throw "Failed to create CI issue in $($entry.Fork)"
                }
            }
        } else {
            Write-Host "CI issue already exists as #$($match[0].number); skipped."
        }
    }

    [pscustomobject]@{
        Fork                 = $entry.Fork
        Parent               = $actualParent
        ForkDefaultBranch    = $repo.default_branch
        ParentDefaultBranch  = $upstream.default_branch
        ForkIssuesBefore     = [bool]$repo.has_issues
        ParentIssues         = [bool]$upstream.has_issues
        AiContributionStatus = $aiStatus
        PolicyFilesFound     = ($policyHits.Path -join ', ')
    }
}

Write-Host "`n=== Summary ===" -ForegroundColor Cyan
$results | Format-Table -AutoSize

Write-Host @'

Interpretation rule:
  UNKNOWN_NO_EXPLICIT_REPO_POLICY_FOUND means exactly that: upstream AI acceptance
  has NOT been established. Do not send AI-written/materially AI-assisted changes
  upstream until the intended upstream maintainer explicitly allows them or an
  authoritative policy says so.

Useful invocations:
  # Audit only; no changes
  ./Repair-UpstreamForks.ps1 -AuditOnly

  # Enable Issues on the three forks
  ./Repair-UpstreamForks.ps1

  # Enable Issues and create the fork-local CI work items idempotently
  ./Repair-UpstreamForks.ps1 -CreateCiIssues

  # Preview mutations
  ./Repair-UpstreamForks.ps1 -CreateCiIssues -WhatIf
'@
