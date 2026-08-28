[CmdletBinding()]
param(
    [Parameter(Mandatory=$true)][string]$Root,
    [Parameter(Mandatory=$true)][string]$OutputPath,
    [string]$Lane = 'unknown',
    [switch]$FailOnParseError
)

Set-StrictMode -Version 2.0
$ErrorActionPreference = 'Stop'

$resolvedRoot = (Resolve-Path -LiteralPath $Root).Path
$runtime = [ordered]@{
    lane = $Lane
    psVersion = $PSVersionTable.PSVersion.ToString()
    psEdition = if ($PSVersionTable.ContainsKey('PSEdition')) { [string]$PSVersionTable.PSEdition } else { 'Desktop' }
    platform = if ($PSVersionTable.ContainsKey('Platform')) { [string]$PSVersionTable.Platform } else { 'Win32NT' }
    os = if ($PSVersionTable.ContainsKey('OS')) { [string]$PSVersionTable.OS } else { [Environment]::OSVersion.VersionString }
}

$riskyCommands = @(
    'Invoke-Expression','Add-Type','Start-Process','Invoke-WebRequest','Invoke-RestMethod',
    'Start-BitsTransfer','Register-ScheduledTask','New-ScheduledTaskAction','Set-ExecutionPolicy',
    'Set-ItemProperty','Remove-Item','Remove-ItemProperty'
)

$files = @(Get-ChildItem -LiteralPath $resolvedRoot -Recurse -File | Where-Object {
    $_.Extension -in @('.ps1','.psm1','.psd1')
} | Sort-Object FullName)

$results = @()
foreach ($file in $files) {
    $tokens = $null
    $errors = $null
    $ast = [System.Management.Automation.Language.Parser]::ParseFile($file.FullName, [ref]$tokens, [ref]$errors)
    $relative = $file.FullName.Substring($resolvedRoot.Length).TrimStart([IO.Path]::DirectorySeparatorChar, [IO.Path]::AltDirectorySeparatorChar)
    $hash = (Get-FileHash -LiteralPath $file.FullName -Algorithm SHA256).Hash.ToLowerInvariant()

    $diagnostics = @($errors | ForEach-Object {
        [ordered]@{
            message = $_.Message; errorId = $_.ErrorId
            startLine = $_.Extent.StartLineNumber; startColumn = $_.Extent.StartColumnNumber
            endLine = $_.Extent.EndLineNumber; endColumn = $_.Extent.EndColumnNumber
            text = $_.Extent.Text
        }
    })

    $risks = @()
    $commands = @($ast.FindAll({ param($node) $node -is [System.Management.Automation.Language.CommandAst] }, $true))
    foreach ($command in $commands) {
        $name = $command.GetCommandName()
        if ($name -and ($name -in $riskyCommands)) {
            $risks += [ordered]@{ kind='command-heuristic'; command=$name; line=$command.Extent.StartLineNumber; note='Review required; heuristic finding is not proof of unsafe behavior.' }
        }
        if (-not $name) {
            $risks += [ordered]@{ kind='dynamic-command'; command=$null; line=$command.Extent.StartLineNumber; note='Dynamic command invocation reduces static assurance.' }
        }
    }

    $results += [ordered]@{
        path = ($relative -replace '\\','/')
        sha256 = $hash
        parseCompatible = ($diagnostics.Count -eq 0)
        parserDiagnostics = $diagnostics
        riskHeuristics = $risks
    }
}

$document = [ordered]@{
    schemaVersion = '1.0'
    generatedAtUtc = [DateTime]::UtcNow.ToString('o')
    root = $resolvedRoot
    runtime = $runtime
    fileCount = $results.Count
    parsePassCount = @($results | Where-Object { $_.parseCompatible }).Count
    parseFailCount = @($results | Where-Object { -not $_.parseCompatible }).Count
    heuristicFindingCount = (@($results | ForEach-Object { $_.riskHeuristics })).Count
    files = $results
    semantics = [ordered]@{
        parseCompatibility = 'Evidence that this runtime parser accepted the source.'
        safety = 'Risk findings are heuristics only; absence of findings is not a safety proof.'
        behavioralEquivalence = 'Not evaluated by this scanner.'
    }
}

$outputDir = Split-Path -Parent $OutputPath
if ($outputDir -and -not (Test-Path -LiteralPath $outputDir)) { New-Item -ItemType Directory -Path $outputDir -Force | Out-Null }
$document | ConvertTo-Json -Depth 12 | Set-Content -LiteralPath $OutputPath -Encoding UTF8
Write-Host ('Lane: {0}; files: {1}; parse failures: {2}; heuristic findings: {3}' -f $Lane, $document.fileCount, $document.parseFailCount, $document.heuristicFindingCount)
if ($FailOnParseError -and $document.parseFailCount -gt 0) { exit 2 }
exit 0
