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
Import-Module (Join-Path $PSScriptRoot 'PSGitLiteDle.psm1') -Force
Import-Module (Join-Path $PSScriptRoot 'PSGitLiteRecoveryV2.psm1')
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
      # Baton content is read from a Git object, not an instruction or grant.
      # Render it as one escaped JSON string so CR/LF/ANSI controls cannot
      # forge additional human-facing status lines.
      $quoted=ConvertTo-Json -InputObject ([string]$out.nextBaton) -Compress
      Write-Output ('Next baton (untrusted, escaped): '+$quoted)
    }
  }
  'Json' {Write-Output (ConvertTo-Json -InputObject $out -Depth 8 -Compress)}
  'Jsonl' {Write-Output (ConvertTo-Json -InputObject $out -Depth 8 -Compress)}
}
