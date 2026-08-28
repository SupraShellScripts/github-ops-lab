[CmdletBinding()]
param(
    [Parameter(Mandatory=$true)][string]$ResultsRoot,
    [Parameter(Mandatory=$true)][string]$OutputPath,
    [switch]$RequireWinPS51AndPS7
)

Set-StrictMode -Version 2.0
$ErrorActionPreference = 'Stop'

$documents = @{}
Get-ChildItem -LiteralPath $ResultsRoot -Recurse -Filter '*.json' -File | ForEach-Object {
    $doc = Get-Content -LiteralPath $_.FullName -Raw | ConvertFrom-Json
    if ($doc.runtime -and $doc.runtime.lane) {
        $documents[[string]$doc.runtime.lane] = $doc
    }
}

$required = @('winps51-windows','ps7-windows')
$missing = @($required | Where-Object { -not $documents.ContainsKey($_) })
if ($RequireWinPS51AndPS7 -and $missing.Count -gt 0) {
    throw ('Missing required lane evidence: ' + ($missing -join ', '))
}

$allPaths = @($documents.Values | ForEach-Object { $_.files | ForEach-Object { $_.path } } | Sort-Object -Unique)
$rows = @()
foreach ($path in $allPaths) {
    $laneStates = [ordered]@{}
    foreach ($lane in @($documents.Keys | Sort-Object)) {
        $entry = @($documents[$lane].files | Where-Object { $_.path -eq $path }) | Select-Object -First 1
        if ($entry) {
            $laneStates[$lane] = [ordered]@{
                sha256 = $entry.sha256
                parseCompatible = [bool]$entry.parseCompatible
                diagnosticCount = @($entry.parserDiagnostics).Count
                heuristicFindingCount = @($entry.riskHeuristics).Count
            }
        }
    }

    $win = if ($documents.ContainsKey('winps51-windows')) { @($documents['winps51-windows'].files | Where-Object { $_.path -eq $path }) | Select-Object -First 1 } else { $null }
    $ps7 = if ($documents.ContainsKey('ps7-windows')) { @($documents['ps7-windows'].files | Where-Object { $_.path -eq $path }) | Select-Object -First 1 } else { $null }
    $crossEngine = $null
    if ($win -and $ps7) { $crossEngine = ([bool]$win.parseCompatible -and [bool]$ps7.parseCompatible) }

    $rows += [ordered]@{
        path = $path
        crossEngineParseCompatible = $crossEngine
        lanes = $laneStates
    }
}

$crossEngineFailures = @($rows | Where-Object { $_.crossEngineParseCompatible -eq $false })
$hashDrift = @()
foreach ($row in $rows) {
    $hashes = @($row.lanes.Values | ForEach-Object { $_.sha256 } | Sort-Object -Unique)
    if ($hashes.Count -gt 1) { $hashDrift += $row.path }
}

$result = [ordered]@{
    schemaVersion = '1.0'
    generatedAtUtc = [DateTime]::UtcNow.ToString('o')
    evidenceLevel = if ($crossEngineFailures.Count -eq 0 -and $missing.Count -eq 0) { 'parse-compatible' } else { 'incompatible-or-incomplete' }
    behavioralEquivalence = 'not-evaluated'
    requiredLanes = $required
    missingRequiredLanes = $missing
    crossEngineParseFailureCount = $crossEngineFailures.Count
    sourceHashDrift = $hashDrift
    files = $rows
    semantics = [ordered]@{
        parseCompatible = 'Both real Windows PowerShell 5.1 and PowerShell 7 Windows parsers accepted the same source bytes.'
        behavioralEquivalence = 'Requires project-declared tests executed in both engines; this report does not infer it from parsing.'
        safety = 'Heuristic findings require review and do not constitute a safety proof.'
    }
}

$outputDir = Split-Path -Parent $OutputPath
if ($outputDir -and -not (Test-Path -LiteralPath $outputDir)) { New-Item -ItemType Directory -Path $outputDir -Force | Out-Null }
$result | ConvertTo-Json -Depth 14 | Set-Content -LiteralPath $OutputPath -Encoding UTF8

Write-Host ('Evidence level: {0}; cross-engine parse failures: {1}; missing lanes: {2}' -f $result.evidenceLevel, $result.crossEngineParseFailureCount, $result.missingRequiredLanes.Count)
if ($result.sourceHashDrift.Count -gt 0) { throw ('Source hash drift across lanes: ' + ($result.sourceHashDrift -join ', ')) }
if ($RequireWinPS51AndPS7 -and ($result.crossEngineParseFailureCount -gt 0 -or $result.missingRequiredLanes.Count -gt 0)) { exit 2 }
exit 0
