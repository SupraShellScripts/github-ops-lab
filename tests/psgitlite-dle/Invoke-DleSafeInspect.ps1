#requires -Version 5.1
<#
.SYNOPSIS
  Read-only DLE safe resume inspection. NO external action and NO approval claim.
.DESCRIPTION
  Intended for future bounded AIrea51 integration, NOT an active runtime hook.
  V1 ambiguous effects fail closed, v2 effectId chain is checked end-to-end.
#>
[CmdletBinding()]param(
  [Parameter(Mandatory)][string]$RepositoryPath,
  [Parameter(Mandatory)][string]$WorksetId,
  [ValidateSet('Human','Json','Jsonl')][string]$Format='Human'
)
Set-StrictMode -Version Latest
$ErrorActionPreference='Stop'
# The recovery module resolves DLE commands by name, so both imports
# must be visible during the call. Preserve any caller-owned modules and clean
# up only those this observer introduces after rendering (success or failure).
$enginePath=Join-Path $PSScriptRoot 'PSGitLiteDle.psm1'
$recoveryPath=Join-Path $PSScriptRoot 'PSGitLiteRecoveryV2.psm1'
$corePath=Join-Path (Split-Path $PSScriptRoot -Parent) 'psgitlite-native/PSGitLiteCore.psm1'
$modulePaths=@($enginePath,$recoveryPath,$corePath)
$alreadyLoaded=@{}
foreach($modulePath in $modulePaths){
  $alreadyLoaded[$modulePath]=@(
    Get-Module | Where-Object { $_.Path -ceq $modulePath }
  ).Count -gt 0
}
try {
Import-Module $enginePath -ErrorAction Stop
Import-Module $recoveryPath -ErrorAction Stop
$decision=Get-PSGitLiteDleSafeResume -RepositoryPath $RepositoryPath -WorksetId $WorksetId
$assessment=$decision.Assessment
$pending=@()
$failures=@()
$legacy=@()
$count=0
if($null -ne $assessment){
  $pending=@($assessment.PendingEffects | ForEach-Object { [string]$_.EffectId })
  $failures=@($assessment.FailedEffects | ForEach-Object {
    if($null -ne $_.PSObject.Properties['EffectId']){[string]$_.EffectId}
    else{[string]$_.RequestId}
  })
  $legacy=@($assessment.LegacyUncorrelated | ForEach-Object { [string]$_.RequestId })
  $count=[int]$assessment.EventCount
}
$out=[ordered]@{
  schemaVersion='psgitlite.dle-safe-inspect.v1'
  worksetId=$WorksetId
  head=$decision.Head
  verdict=$decision.Verdict
  eventCount=$count
  pendingEffects=@($pending)
  failedEffects=@($failures)
  legacyUncorrelated=@($legacy)
  autoReexecuteAllowed=$false
  authority='OBSERVATION_ONLY'
  nextBaton=$(if($null -ne $decision.PSObject.Properties['NextBaton']){$decision.NextBaton}else{$null})
}
switch($Format){
  'Human' {
    Write-Output ('DLE '+$WorksetId+' verdict='+$out.verdict+' head='+$out.head)
    Write-Output ('Pending='+$pending.Count+' Failed='+$failures.Count+' Legacy='+$legacy.Count)
    Write-Output 'Auto-execute: DENIED'
    if($out.nextBaton){
      # Git baton contents are untrusted. Do not emit raw terminal controls
      # or multiline status-looking output from the Human renderer.
      $quoted=ConvertTo-Json -InputObject ([string]$out.nextBaton) -Compress
      Write-Output ('Next baton (untrusted, escaped): '+$quoted)
    }
  }
  'Json' {Write-Output (ConvertTo-Json -InputObject $out -Depth 8 -Compress)}
  'Jsonl' {Write-Output (ConvertTo-Json -InputObject $out -Depth 8 -Compress)}
}
}finally {
  # Never unload a module that was already present in the caller's session.
  # The order matters because the DLE module itself imports PSGitLiteCore.
  foreach($modulePath in @($recoveryPath,$enginePath,$corePath)){
    if(-not $alreadyLoaded[$modulePath]){
      $newModules=@(Get-Module | Where-Object { $_.Path -ceq $modulePath })
      foreach($module in $newModules){
        Remove-Module -ModuleInfo $module -Force -ErrorAction SilentlyContinue
      }
    }
  }
}
