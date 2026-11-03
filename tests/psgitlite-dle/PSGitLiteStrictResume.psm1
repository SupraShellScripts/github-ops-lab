#requires -Version 5.1
# Read-only fail-closed recovery guard for legacy PSGitLite DLE events.
# Does NOT change the existing writer, claim authorization or execute actions.
Set-StrictMode -Version Latest
$ErrorActionPreference='Stop'
Import-Module (Join-Path $PSScriptRoot 'PSGitLiteDle.psm1') -Force
function Get-GitLiteDleStrictResume {
  [CmdletBinding()]param([Parameter(Mandatory)][string]$RepositoryPath,
    [Parameter(Mandatory)][string]$WorksetId)
  $snapshot=Get-GitLiteDleSnapshot -RepositoryPath $RepositoryPath -WorksetId $WorksetId
  if(!$snapshot.Head){
    $verdict=if($snapshot.Recovery -ceq 'LOCK_RECONCILE_REQUIRED'){'RECONCILE_REQUIRED'}else{'CREATE_CHECKPOINT'}
    return [pscustomobject]@{Head=$null;Verdict=$verdict;LegacyUncorrelated=@();Failures=@();AutoReexecuteAllowed=$false}
  }
  $history=@(Get-GitLiteDleHistory -RepositoryPath $RepositoryPath -WorksetId $WorksetId -MaxCount 128)
  if($history.Count -eq 0 -or $history[0].Head -cne $snapshot.Head){throw 'DLE_HISTORY_RACE'}
  if($history[$history.Count-1].Parent){throw 'DLE_HISTORY_INCOMPLETE'}
  $uncertain=@()
  $failures=@()
  foreach($item in $history){
    $event=$item.Event
    if($event.schemaVersion -cne 'airea51.dle-event.v1'){throw 'DLE_UNQUALIFIED_EVENT_FORMAT'}
    $status=[string]$event.status
    if($status -ceq 'FAILED'){$failures+=@([string]$event.requestId)}
    elseif($status -in @('INTENT','OBSERVED','UNKNOWN')){
      $uncertain+=@([string]$event.requestId)
    }
  }
  $verdict=if($failures.Count -gt 0){'DIAGNOSE_FIRST_FAILURE'}
    elseif($uncertain.Count -gt 0){'RECONCILE_REQUIRED'}
    else{'CONTINUE_FROM_BATON'}
  if($snapshot.Recovery -ceq 'LOCK_RECONCILE_REQUIRED'){$verdict='RECONCILE_REQUIRED'}
  return [pscustomobject]@{Head=$snapshot.Head;Verdict=$verdict;
    LegacyUncorrelated=@($uncertain);Failures=@($failures);
    NextBaton=$snapshot.NextBaton;AutoReexecuteAllowed=$false;
    Source='complete-v1-history-conservative-guard'}
}
Export-ModuleMember -Function Get-GitLiteDleStrictResume
