#requires -Version 5.1
# Public-original synthetic PSGitLite effect-correlation assessor.
# Read-only. NO automatic external action, signature validation or network.
Set-StrictMode -Version Latest
$ErrorActionPreference='Stop'

function Get-PSGitLiteRecoveryDecision {
  [CmdletBinding()]param([AllowEmptyCollection()][object[]]$Events=@())
  $states=[Collections.Generic.Dictionary[string,string]]::new([StringComparer]::Ordinal)
  $requests=[Collections.Generic.HashSet[string]]::new([StringComparer]::Ordinal)
  $legacy=New-Object Collections.ArrayList
  $failed=New-Object Collections.ArrayList
  $pendingNonEffect=New-Object Collections.ArrayList
  $count=0
  $latest=$null
  $workset=$null
  foreach($event in @($Events)){
    if($null -eq $event){throw 'DLE_NULL_EVENT'}
    $count++
    if($count -gt 128){throw 'DLE_HISTORY_BOUND'}
    $status=[string]$event.status
    $request=[string]$event.requestId
    $version=[string]$event.schemaVersion
    if($status -cnotin @('INTENT','OBSERVED','VERIFIED','FAILED','UNKNOWN')){throw 'DLE_INVALID_STATUS'}
    if($request -cnotmatch '^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$' -or !$requests.Add($request)){
      throw 'DLE_REQUEST_INVALID_OR_DUPLICATE'
    }
    $latest=$status
    if($version -ceq 'airea51.dle-event.v1'){
      # Legacy has no authenticated effect correlation. Even a later VERIFIED
      # unrelated event cannot close earlier uncertain external side effects.
      if($status -in @('INTENT','OBSERVED','UNKNOWN','FAILED')){
        $entry=[pscustomobject]@{RequestId=$request;Reason='UNCORRELATED_V1_EVENT';Status=$status}
        [void]$legacy.Add($entry)
        if($status -ceq 'FAILED'){[void]$failed.Add($entry)}
      }
      continue
    }
    if($version -cne 'airea51.dle-event.v2'){throw 'DLE_UNKNOWN_SCHEMA_VERSION'}
    $ws=[string]$event.worksetId
    if($ws -cnotmatch '^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$'){throw 'DLE_V2_WORKSET_REQUIRED'}
    if($null -eq $workset){$workset=$ws}
    if($ws -cne $workset){throw 'DLE_CROSS_WORKSET_EVENT'}
    $kind=[string]$event.eventKind
    if($kind -cnotin @('EXTERNAL_EFFECT','PASSIVE_OBSERVATION','DECISION','CHECKPOINT')){
      throw 'DLE_INVALID_EVENT_KIND'
    }
    $phase=[string]$event.phase
    if($phase -cnotin @('Discover','Observe','Plan','Apply','Verify','Reconcile')){throw 'DLE_INVALID_PHASE'}
    if($kind -cne 'EXTERNAL_EFFECT'){
      if($status -in @('INTENT','UNKNOWN')){
        throw 'DLE_NON_EFFECT_AMBIGUOUS_STATUS'
      }
      if($status -ceq 'FAILED'){
        [void]$failed.Add([pscustomobject]@{RequestId=$request;Reason='NON_EFFECT_FAILURE';Status=$status})
      }
      continue
    }
    $effect=[string]$event.effectId
    if($effect -cnotmatch '^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$'){throw 'DLE_EFFECT_ID_REQUIRED'}
    if(!$states.ContainsKey($effect)){
      if($status -cne 'INTENT' -or $phase -cne 'Apply'){throw 'DLE_EFFECT_WITHOUT_APPLY_INTENT'}
      $states.Add($effect,'INTENT')
      continue
    }
    $old=$states[$effect]
    if($old -ceq 'VERIFIED'){throw 'DLE_TERMINAL_EFFECT_REUSED'}
    if($status -ceq 'INTENT'){throw 'DLE_DUPLICATE_EFFECT_INTENT'}
    if($old -ceq 'FAILED' -and $status -cne 'VERIFIED'){
      throw 'DLE_FAILED_EFFECT_CANNOT_DOWNGRADE'
    }
    if($status -ceq 'VERIFIED'){
      if($phase -cnotin @('Verify','Reconcile')){throw 'DLE_VERIFICATION_PHASE_DENIED'}
      if($old -ceq 'FAILED' -and $phase -cne 'Reconcile'){
        throw 'DLE_FAILED_REQUIRES_RECONCILE'
      }
      $refs=@()
      if($null -ne $event.PSObject.Properties['evidenceRefs'] -and $null -ne $event.evidenceRefs){
        $refs=@($event.evidenceRefs)
      }
      if($refs.Count -eq 0){throw 'DLE_VERIFICATION_WITHOUT_EVIDENCE'}
      foreach($ref in $refs){
        if([string]::IsNullOrWhiteSpace([string]$ref) -or ([string]$ref).Length -gt 256){
          throw 'DLE_BAD_VERIFICATION_EVIDENCE'
        }
      }
    }
    $states[$effect]=$status
  }
  $pending=New-Object Collections.ArrayList
  foreach($name in $states.Keys){
    $status=$states[$name]
    if($status -ceq 'FAILED'){
      [void]$failed.Add([pscustomobject]@{EffectId=$name;Status=$status;Reason='FAILED_EFFECT'})
    }elseif($status -cne 'VERIFIED'){
      [void]$pending.Add([pscustomobject]@{EffectId=$name;Status=$status;Reason='UNVERIFIED_EFFECT'})
    }
  }
  $p=@($pending | Sort-Object -Property EffectId)
  $f=@($failed | Sort-Object -Property EffectId,RequestId)
  $l=@($legacy | Sort-Object -Property RequestId)
  $verdict='CONTINUE_FROM_BATON'
  if($f.Count -gt 0){$verdict='DIAGNOSE_FIRST_FAILURE'}
  elseif($p.Count -gt 0 -or $l.Count -gt 0){$verdict='RECONCILE_REQUIRED'}
  return [pscustomobject]@{
    SchemaVersion='psgitlite.recovery-assessment.v2'
    Verdict=$verdict
    EventCount=$count
    LatestStatus=$latest
    PendingEffects=$p
    FailedEffects=$f
    LegacyUncorrelated=$l
    AutoReexecuteAllowed=$false
    Source='full-history-effect-correlated'
  }
}

function Get-PSGitLiteDleSafeResume {
  [CmdletBinding()]param([Parameter(Mandatory)][string]$RepositoryPath,
    [Parameter(Mandatory)][string]$WorksetId)
  # Caller must import the DLE module; no nested -Force import/reload side effects.
  if(-not (Get-Command Get-GitLiteDleSnapshot -ErrorAction SilentlyContinue)){
    throw 'DLE_CORE_NOT_IMPORTED'
  }
  $snap=Get-GitLiteDleSnapshot -RepositoryPath $RepositoryPath -WorksetId $WorksetId
  if(!$snap.Head){
    $v=if($snap.Recovery -ceq 'LOCK_RECONCILE_REQUIRED'){'RECONCILE_REQUIRED'}else{'CREATE_CHECKPOINT'}
    return [pscustomobject]@{Head=$null;Verdict=$v;Assessment=$null;AutoReexecuteAllowed=$false}
  }
  $items=@(Get-GitLiteDleHistory -RepositoryPath $RepositoryPath -WorksetId $WorksetId -MaxCount 128)
  if($items.Count -eq 0 -or $items[0].Head -cne $snap.Head){throw 'DLE_HISTORY_RACE'}
  if($items[$items.Count-1].Parent){throw 'DLE_HISTORY_INCOMPLETE'}
  [array]::Reverse($items)
  $decision=Get-PSGitLiteRecoveryDecision -Events @($items | ForEach-Object {$_.Event})
  $v=$decision.Verdict
  if($snap.Recovery -ceq 'LOCK_RECONCILE_REQUIRED'){$v='RECONCILE_REQUIRED'}
  return [pscustomobject]@{Head=$snap.Head;Verdict=$v;
    Assessment=$decision;NextBaton=$snap.NextBaton;AutoReexecuteAllowed=$false}
}
Export-ModuleMember -Function Get-PSGitLiteRecoveryDecision,Get-PSGitLiteDleSafeResume
