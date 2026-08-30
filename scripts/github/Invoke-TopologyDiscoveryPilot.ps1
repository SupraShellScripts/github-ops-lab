[CmdletBinding()]
param(
    [Parameter(Mandatory)]
    [ValidatePattern('^[A-Za-z0-9-]+$')]
    [string]$Organization,

    [Parameter()]
    [string]$OutputDirectory = (Join-Path $PWD '.local/topology-discovery-pilot'),

    [Parameter()]
    [ValidateSet('minimal','medium','full')]
    [string]$StatsMode = 'medium',

    [Parameter()]
    [switch]$RunRepoMap,

    [Parameter()]
    [switch]$InstallMissing
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

function Assert-Command {
    param([Parameter(Mandatory)][string]$Name)
    if (-not (Get-Command $Name -ErrorAction SilentlyContinue)) {
        throw "Required command '$Name' was not found on PATH."
    }
}

function Test-GhExtensionInstalled {
    param([Parameter(Mandatory)][string]$Repository)
    $listed = (& gh extension list 2>$null | Out-String)
    return $listed -match [regex]::Escape($Repository)
}

function Ensure-GhExtension {
    param([Parameter(Mandatory)][string]$Repository)
    if (Test-GhExtensionInstalled $Repository) { return }
    if (-not $InstallMissing) {
        throw "Required GitHub CLI extension '$Repository' is not installed. Re-run with -InstallMissing after reviewing the upstream extension."
    }
    & gh extension install $Repository
    if ($LASTEXITCODE -ne 0) { throw "Unable to install $Repository." }
}

Assert-Command gh
Ensure-GhExtension 'mona-actions/gh-stats'
if ($RunRepoMap) { Ensure-GhExtension 'mona-actions/gh-repo-map' }

$root = [IO.Path]::GetFullPath($OutputDirectory)
New-Item -ItemType Directory -Force -Path $root | Out-Null
$raw = Join-Path $root 'raw'
New-Item -ItemType Directory -Force -Path $raw | Out-Null

$run = [ordered]@{
    schema_version = 1
    organization = $Organization
    started_at_utc = [DateTimeOffset]::UtcNow.ToString('o')
    stats_mode = $StatsMode
    repo_map_requested = [bool]$RunRepoMap
    commands = @()
}

$statsPath = Join-Path $raw 'gh-stats.json'
$statsArgs = @('stats','--org',$Organization,'--output',$statsPath)
switch ($StatsMode) {
    'minimal' { $statsArgs += '--minimal' }
    'medium' {
        # Migration-oriented balance: retain Actions/settings/rulesets/Pages and issue/PR
        # metadata while skipping high-cost telemetry/source-tree collection that is not
        # required for the first topology pass.
        $statsArgs += @('--no-packages','--no-traffic','--no-lfs','--no-files','--no-contributors','--no-commits')
    }
    'full' { }
}

$run.commands += ('gh ' + ($statsArgs -join ' '))
& gh @statsArgs
if ($LASTEXITCODE -ne 0) { throw "gh-stats failed with exit code $LASTEXITCODE." }
if (-not (Test-Path -LiteralPath $statsPath)) { throw "gh-stats did not produce $statsPath" }

if ($RunRepoMap) {
    $repoMapDir = Join-Path $raw 'gh-repo-map'
    New-Item -ItemType Directory -Force -Path $repoMapDir | Out-Null
    $orgsFile = Join-Path $repoMapDir 'orgs.txt'
    $Organization | Set-Content -LiteralPath $orgsFile -Encoding utf8

    Push-Location $repoMapDir
    try {
        $mapArgs = @('repo-map','--orgs-file',$orgsFile,'--include-transitive','--clean-checkpoints')
        $run.commands += ('gh ' + ($mapArgs -join ' '))
        & gh @mapArgs
        if ($LASTEXITCODE -ne 0) { throw "gh-repo-map failed with exit code $LASTEXITCODE." }
    }
    finally {
        Pop-Location
    }
}

$run.completed_at_utc = [DateTimeOffset]::UtcNow.ToString('o')
$run | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath (Join-Path $root 'run-receipt.json') -Encoding utf8

Write-Host "Discovery pilot complete: $root"
Write-Host 'Raw output may contain private repository/access/topology information. Keep it outside public repositories and public Actions artifacts.'
