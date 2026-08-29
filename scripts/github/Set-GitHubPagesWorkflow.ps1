#requires -Version 7.0
<#
.SYNOPSIS
  Configure a public GitHub repository to publish GitHub Pages with GitHub Actions.

.DESCRIPTION
  Idempotently configures the repository's GitHub Pages build type to `workflow`,
  which is the REST API equivalent of selecting Settings > Pages > Source >
  GitHub Actions.

  The script is intentionally bounded:
    * public repositories only;
    * one explicitly named repository per invocation;
    * read-only unless mutation is requested;
    * mutations require GH_MUTATION_TOKEN;
    * -AuditOnly and -WhatIf never change repository settings;
    * post-mutation verification fails closed if GitHub does not report
      build_type=workflow.

  This script does not create a Pages deployment workflow. The target repository
  remains responsible for its own .github/workflows Pages deployment definition.
#>

[CmdletBinding(SupportsShouldProcess)]
param(
    [Parameter(Mandatory, Position = 0)]
    [ValidatePattern('^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$')]
    [string]$Repository,

    [switch]$AuditOnly
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
    if (-not $raw) {
        return $null
    }
    return ($raw | Out-String | ConvertFrom-Json)
}

function Get-GitHubPagesSite {
    param(
        [Parameter(Mandatory)][string]$Repo
    )

    $raw = & gh api "repos/$Repo/pages" 2>&1
    $exitCode = $LASTEXITCODE

    if ($exitCode -eq 0) {
        if (-not $raw) {
            throw "GitHub returned an empty Pages response for $Repo."
        }
        return ($raw | Out-String | ConvertFrom-Json)
    }

    $message = ($raw | Out-String)
    if ($message -match '(?i)HTTP\s+404|Not Found') {
        # A repository without a configured Pages site is a normal probe result.
        # Do not allow gh's expected 404 to leak into the script process exit code.
        $global:LASTEXITCODE = 0
        return $null
    }

    throw "Unable to read GitHub Pages settings for ${Repo}:`n$message"
}

function Invoke-GhMutation {
    param(
        [Parameter(Mandatory)][string[]]$Args
    )

    if (-not $env:GH_MUTATION_TOKEN) {
        throw 'Mutation requested but GH_MUTATION_TOKEN is not set.'
    }

    $readToken = $env:GH_TOKEN
    try {
        $env:GH_TOKEN = $env:GH_MUTATION_TOKEN
        & gh @Args
        if ($LASTEXITCODE -ne 0) {
            throw "gh $($Args -join ' ') mutation failed."
        }
    }
    finally {
        $env:GH_TOKEN = $readToken
    }
}

& gh auth status
if ($LASTEXITCODE -ne 0) {
    throw 'GitHub CLI is not authenticated. Run: gh auth login'
}

$repo = Invoke-GhJson -Args @('api', "repos/$Repository")
if ([string]$repo.visibility -ne 'public') {
    throw "$Repository is not public; this public-safe helper refuses to operate on it."
}
if ([bool]$repo.archived) {
    throw "$Repository is archived; refusing to change Pages settings."
}

$pages = Get-GitHubPagesSite -Repo $Repository
$currentBuildType = if ($null -eq $pages) { 'not-configured' } else { [string]$pages.build_type }

Write-Host "Repository:       $Repository"
Write-Host "Visibility:       $($repo.visibility)"
Write-Host "Pages build type: $currentBuildType"

if ($currentBuildType -eq 'workflow') {
    Write-Host 'GitHub Pages already uses GitHub Actions; no change is required.' -ForegroundColor Green
    [pscustomobject]@{
        Repository = $Repository
        Before = 'workflow'
        After = 'workflow'
        Changed = $false
        Mode = if ($AuditOnly) { 'audit' } else { 'apply' }
    }
    return
}

if ($AuditOnly) {
    Write-Host 'Audit only: GitHub Pages is not configured for GitHub Actions.' -ForegroundColor Yellow
    [pscustomobject]@{
        Repository = $Repository
        Before = $currentBuildType
        After = $currentBuildType
        Changed = $false
        Mode = 'audit'
    }
    return
}

$action = if ($null -eq $pages) {
    'Create GitHub Pages site with GitHub Actions as the build source'
} else {
    "Change GitHub Pages build type from '$currentBuildType' to 'workflow'"
}

if ($PSCmdlet.ShouldProcess($Repository, $action)) {
    if ($null -eq $pages) {
        Invoke-GhMutation -Args @(
            'api', '--method', 'POST', "repos/$Repository/pages",
            '-f', 'build_type=workflow', '--silent'
        )
    }
    else {
        Invoke-GhMutation -Args @(
            'api', '--method', 'PUT', "repos/$Repository/pages",
            '-f', 'build_type=workflow', '--silent'
        )
    }

    $verified = Get-GitHubPagesSite -Repo $Repository
    if ($null -eq $verified -or [string]$verified.build_type -ne 'workflow') {
        $observed = if ($null -eq $verified) { 'not-configured' } else { [string]$verified.build_type }
        throw "Pages mutation did not verify. Expected build_type=workflow, observed '$observed'."
    }

    Write-Host 'GitHub Pages now uses GitHub Actions.' -ForegroundColor Green
    [pscustomobject]@{
        Repository = $Repository
        Before = $currentBuildType
        After = 'workflow'
        Changed = $true
        Mode = 'apply'
    }
}

<#
Examples:

  # Read-only inspection
  ./scripts/github/Set-GitHubPagesWorkflow.ps1 SupraCraft/VanillaCord -AuditOnly

  # Preview the mutation
  ./scripts/github/Set-GitHubPagesWorkflow.ps1 SupraCraft/VanillaCord -WhatIf

  # Apply. Keep a read token in GH_TOKEN if desired; mutations use the separately
  # supplied narrowly scoped GH_MUTATION_TOKEN.
  $env:GH_MUTATION_TOKEN = '<token with Pages + Administration write for the target repo>'
  ./scripts/github/Set-GitHubPagesWorkflow.ps1 SupraCraft/VanillaCord
#>
