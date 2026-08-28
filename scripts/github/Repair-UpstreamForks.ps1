#requires -Version 7.0
<#
.SYNOPSIS
  Stable public entry point for upstream-fork audit and maintenance.

.DESCRIPTION
  This public entry point delegates to the byte-validated implementation kept in
  candidates/Repair-UpstreamForks.ps1. It exists so operators and workflows have
  a durable scripts/github path while the candidate remains available as the
  exact validation/provenance object.
#>

[CmdletBinding(SupportsShouldProcess)]
param(
    [switch]$AuditOnly,
    [switch]$CreateCiIssues,
    [ValidateSet('SupraCraft/VanillaCord', 'SupraCraft/Bridge', 'SemperSupra/OpenXcom')]
    [string[]]$Fork
)

$implementation = Join-Path $PSScriptRoot '..' '..' 'candidates' 'Repair-UpstreamForks.ps1'
$implementation = [IO.Path]::GetFullPath($implementation)

if (-not (Test-Path -LiteralPath $implementation -PathType Leaf)) {
    throw "Validated implementation not found: $implementation"
}

$invoke = @{}
if ($AuditOnly) { $invoke.AuditOnly = $true }
if ($CreateCiIssues) { $invoke.CreateCiIssues = $true }
if ($Fork) { $invoke.Fork = $Fork }
if ($WhatIfPreference) { $invoke.WhatIf = $true }

& $implementation @invoke
if ($LASTEXITCODE -ne 0) {
    exit $LASTEXITCODE
}
