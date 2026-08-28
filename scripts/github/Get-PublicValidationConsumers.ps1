[CmdletBinding()]
param(
    [string[]]$Owners = @('SemperSupra', 'SupraShellScripts', 'SupraCraft', 'mark-e-deyoung'),
    [Parameter(Mandatory = $true)]
    [string]$OutputDirectory,
    [string]$FixtureRoot
)

Set-StrictMode -Version 2.0
$ErrorActionPreference = 'Stop'

function Get-Capability {
    param([Parameter(Mandatory = $true)][string]$Reference)

    $value = $Reference.ToLowerInvariant()
    if ($value -match '^zizmorcore/zizmor-action@') { return 'github-actions-security' }
    if ($value -match '^ossf/scorecard-action@') { return 'repository-security-posture' }
    if ($value -match '^actions/dependency-review-action@') { return 'dependency-review' }
    if ($value -match '^suprashellscripts/github-ops-lab/.github/workflows/powershell-compatibility\.ya?ml@') { return 'powershell-compatibility' }
    if ($value -match '^suprashellscripts/github-ops-lab/.github/workflows/public-fork-maintenance\.ya?ml@') { return 'fork-maintenance' }
    return 'other-action-or-workflow'
}

function Get-PinStatus {
    param([Parameter(Mandatory = $true)][string]$Reference)

    if ($Reference -match '\$\{\{') { return 'dynamic-or-ambiguous' }
    if ($Reference -notmatch '@([^\s#]+)$') { return 'missing-ref' }
    $ref = $Matches[1]
    if ($ref -match '^[0-9a-fA-F]{40}$') { return 'immutable-sha' }
    return 'mutable-ref'
}

function Get-WorkflowRelationships {
    param(
        [Parameter(Mandatory = $true)][string]$Repository,
        [Parameter(Mandatory = $true)][string]$WorkflowPath,
        [Parameter(Mandatory = $true)][string]$Text
    )

    $results = @()
    $lineNumber = 0
    foreach ($line in ($Text -split "`r?`n")) {
        $lineNumber++
        if ($line -notmatch '^\s*uses\s*:\s*(.+?)\s*$') { continue }

        $raw = $Matches[1].Trim()
        if (($raw.StartsWith("'") -and $raw.EndsWith("'")) -or ($raw.StartsWith('"') -and $raw.EndsWith('"'))) {
            $raw = $raw.Substring(1, $raw.Length - 2)
        }

        $status = Get-PinStatus -Reference $raw
        $results += [pscustomobject]@{
            repository   = $Repository
            workflowPath = $WorkflowPath
            line         = $lineNumber
            reference    = $raw
            capability   = Get-Capability -Reference $raw
            pinStatus    = $status
            observation  = if ($status -eq 'dynamic-or-ambiguous') { 'ambiguous-not-asserted' } else { 'observed' }
        }
    }
    return @($results)
}

function Get-PublicRepositoriesForOwner {
    param([Parameter(Mandatory = $true)][string]$Owner)

    $repoJson = & gh api "users/$Owner/repos?per_page=100&type=public&sort=full_name" 2>$null
    if ($LASTEXITCODE -ne 0) { throw "Unable to enumerate public repositories for owner '$Owner'." }
    $repos = @($repoJson | ConvertFrom-Json)
    return @($repos | Where-Object { -not $_.archived } | ForEach-Object { $_.full_name })
}

function Get-RemoteWorkflowFiles {
    param([Parameter(Mandatory = $true)][string]$Repository)

    $listing = & gh api "repos/$Repository/contents/.github/workflows" 2>$null
    if ($LASTEXITCODE -ne 0) {
        $global:LASTEXITCODE = 0
        return @()
    }
    $items = @($listing | ConvertFrom-Json)
    return @($items | Where-Object { $_.type -eq 'file' -and $_.name -match '\.ya?ml$' })
}

function Get-RemoteText {
    param(
        [Parameter(Mandatory = $true)][string]$Repository,
        [Parameter(Mandatory = $true)][string]$Path
    )

    $json = & gh api "repos/$Repository/contents/$Path" 2>$null
    if ($LASTEXITCODE -ne 0) { throw "Unable to read $Repository/$Path" }
    $payload = $json | ConvertFrom-Json
    if ($payload.encoding -ne 'base64') { throw "Unsupported encoding '$($payload.encoding)' for $Repository/$Path" }
    $bytes = [Convert]::FromBase64String(($payload.content -replace '\s', ''))
    return [Text.Encoding]::UTF8.GetString($bytes)
}

$relationships = @()
$repositoriesScanned = @()
$workflowCount = 0

if ($FixtureRoot) {
    $resolved = (Resolve-Path -LiteralPath $FixtureRoot).Path
    $files = @(Get-ChildItem -LiteralPath $resolved -File -Recurse | Where-Object { $_.Name -match '\.ya?ml$' } | Sort-Object FullName)
    $repositoriesScanned += 'fixture/local'
    foreach ($file in $files) {
        $workflowCount++
        $relative = $file.FullName.Substring($resolved.Length).TrimStart([IO.Path]::DirectorySeparatorChar, [IO.Path]::AltDirectorySeparatorChar).Replace('\', '/')
        $text = [IO.File]::ReadAllText($file.FullName)
        $relationships += @(Get-WorkflowRelationships -Repository 'fixture/local' -WorkflowPath $relative -Text $text)
    }
}
else {
    if (-not $env:GH_TOKEN) { throw 'GH_TOKEN is required for public repository discovery.' }
    foreach ($owner in ($Owners | Sort-Object -Unique)) {
        foreach ($repository in (Get-PublicRepositoriesForOwner -Owner $owner)) {
            $repositoriesScanned += $repository
            foreach ($workflow in (Get-RemoteWorkflowFiles -Repository $repository)) {
                $workflowCount++
                $text = Get-RemoteText -Repository $repository -Path $workflow.path
                $relationships += @(Get-WorkflowRelationships -Repository $repository -WorkflowPath $workflow.path -Text $text)
            }
        }
    }
}

$relationships = @($relationships | Sort-Object repository, workflowPath, line, reference)
$repositoriesScanned = @($repositoriesScanned | Sort-Object -Unique)

New-Item -ItemType Directory -Force -Path $OutputDirectory | Out-Null
$jsonPath = Join-Path $OutputDirectory 'public-validation-consumers.json'
$markdownPath = Join-Path $OutputDirectory 'public-validation-consumers.md'

$document = [ordered]@{
    schemaVersion = '1.0'
    authority = 'derived-non-authoritative'
    semantics = [ordered]@{
        sourceOfTruth = 'consumer repository workflows'
        inventory = 'observation only; regenerate instead of hand editing'
        ambiguous = 'dynamic or ambiguous uses references are reported but not asserted as relationships'
    }
    generatedAtUtc = [DateTime]::UtcNow.ToString('o')
    repositoriesScanned = $repositoriesScanned
    workflowCount = $workflowCount
    relationships = $relationships
}
$document | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $jsonPath -Encoding utf8

$lines = @(
    '# Derived public validation consumer inventory',
    '',
    '> This report is generated observation, not configuration. Consumer workflows are authoritative.',
    '',
    "Repositories scanned: $($repositoriesScanned.Count)",
    "Workflow files scanned: $workflowCount",
    "Relationships observed: $($relationships.Count)",
    '',
    '| Repository | Workflow | Capability | Reference | Pin | Observation |',
    '| --- | --- | --- | --- | --- | --- |'
)
foreach ($item in $relationships) {
    $lines += "| $($item.repository) | $($item.workflowPath) | $($item.capability) | $($item.reference) | $($item.pinStatus) | $($item.observation) |"
}
$lines -join "`n" | Set-Content -LiteralPath $markdownPath -Encoding utf8

Write-Host "Wrote $jsonPath"
Write-Host "Wrote $markdownPath"
