param([Parameter(Mandatory)][ValidateSet('prepare','resume','negative')][string]$Mode)
# Public synthetic v2 Git checkpoint qualification across independent interpreters.
Set-StrictMode -Version Latest
$ErrorActionPreference='Stop'
Import-Module (Join-Path $PSScriptRoot 'PSGitLiteDle.psm1') -Force
Import-Module (Join-Path $PSScriptRoot 'PSGitLiteRecoveryV2.psm1')
function Assert([bool]$OK,[string]$Label){if(!$OK){throw ('FAIL '+$Label)};Write-Output ('PASS '+$Label)}
$root=Join-Path $env:RUNNER_TEMP 'psgitlite-v2-store-restart'
if($Mode -eq 'prepare'){
  if([IO.Directory]::Exists($root)){throw 'DLE_FIXTURE_REUSE_REFUSED'}
  $null=Initialize-GitLiteDle -RepositoryPath $root
  $a=New-GitLiteDleCheckpoint -RepositoryPath $root -WorksetId v2demo -RequestId intentA -StepId stepA -Phase Apply -Status INTENT -Message 'synthetic intent A' -NextBaton 'observe A' -SchemaVariant v2 -EventKind EXTERNAL_EFFECT -EffectId effect-A -IntendedEffect 'synthetic marker'
  Assert ($a.Head -cmatch '^[a-f0-9]{40}$') 'first v2 external intent is canonical Git commit'
  $latest=Get-GitLiteDleSnapshot -RepositoryPath $root -WorksetId v2demo
  Assert ($latest.Recovery -ceq 'ASSESSMENT_REQUIRED') 'head-only snapshot cannot authorize v2 continuation'
  $safe=Get-PSGitLiteDleSafeResume -RepositoryPath $root -WorksetId v2demo
  Assert ($safe.Verdict -ceq 'RECONCILE_REQUIRED') 'full history holds unobserved A'
  $b=New-GitLiteDleCheckpoint -RepositoryPath $root -WorksetId v2demo -RequestId unrelatedB -StepId stepB -Phase Verify -Status VERIFIED -Message 'unrelated checkpoint' -NextBaton 'still inspect A' -ExpectedHead $a.Head -SchemaVariant v2 -EventKind CHECKPOINT
  $safe=Get-PSGitLiteDleSafeResume -RepositoryPath $root -WorksetId v2demo
  Assert ($safe.Verdict -ceq 'RECONCILE_REQUIRED' -and $safe.Assessment.PendingEffects.Count -eq 1) 'unrelated verified checkpoint cannot close A'
  $retry=New-GitLiteDleCheckpoint -RepositoryPath $root -WorksetId v2demo -RequestId unrelatedB -StepId stepB -Phase Verify -Status VERIFIED -Message 'unrelated checkpoint' -NextBaton 'still inspect A' -ExpectedHead $a.Head -SchemaVariant v2 -EventKind CHECKPOINT
  Assert ($retry.Replay -and $retry.Head -ceq $b.Head) 'v2 request digest is idempotent'
  Assert (@(Get-GitLiteDleHistory -RepositoryPath $root -WorksetId v2demo).Count -eq 2) 'v2 Git parent history is preserved'
  Write-Output 'PSGITLITE_V2_STORE_PREPARE_PASS'
}
elseif($Mode -eq 'resume'){
  $before=Get-PSGitLiteDleSafeResume -RepositoryPath $root -WorksetId v2demo
  Assert ($before.Verdict -ceq 'RECONCILE_REQUIRED' -and $before.Assessment.PendingEffects.Count -eq 1) 'fresh process reloads pending A'
  $observed=New-GitLiteDleCheckpoint -RepositoryPath $root -WorksetId v2demo -RequestId observedA -StepId stepA -Phase Observe -Status OBSERVED -Message 'observed synthetic A' -NextBaton 'verify A' -ExpectedHead $before.Head -SchemaVariant v2 -EventKind EXTERNAL_EFFECT -EffectId effect-A -ObservedEffect 'marker inspected'
  $middle=Get-PSGitLiteDleSafeResume -RepositoryPath $root -WorksetId v2demo
  Assert ($middle.Verdict -ceq 'RECONCILE_REQUIRED') 'observed does not imply verified'
  $final=New-GitLiteDleCheckpoint -RepositoryPath $root -WorksetId v2demo -RequestId verifyA -StepId stepA -Phase Verify -Status VERIFIED -Message 'verified synthetic A' -NextBaton 'continue synthetic work' -ExpectedHead $observed.Head -SchemaVariant v2 -EventKind EXTERNAL_EFFECT -EffectId effect-A -EvidenceRefs @('fixture:independent-observer') -ObservedEffect 'confirmed'
  $safe=Get-PSGitLiteDleSafeResume -RepositoryPath $root -WorksetId v2demo
  Assert ($safe.Head -ceq $final.Head -and $safe.Verdict -ceq 'CONTINUE_FROM_BATON' -and !$safe.AutoReexecuteAllowed) 'matching evidence-backed verification completes A'
  Assert (@(Get-GitLiteDleHistory -RepositoryPath $root -WorksetId v2demo).Count -eq 4) 'four canonical v2 commits'
  $seen=@(& git -C $root log -4 --format=%H refs/airea51/dle/v2demo)
  Assert ($LASTEXITCODE -eq 0 -and $seen.Count -eq 4 -and $seen[0] -ceq $final.Head) 'independent Git reads v2 commit ancestry'
  $null=@(& git -C $root fsck --full --no-reflogs 2>&1)
  Assert ($LASTEXITCODE -eq 0) 'Git fsck v2 workset repository passes'
  Write-Output 'PSGITLITE_V2_STORE_RESUME_PASS'
}
else {
  $snapshot=Get-GitLiteDleSnapshot -RepositoryPath $root -WorksetId v2demo
  $refused=$false
  try{$null=New-GitLiteDleCheckpoint -RepositoryPath $root -WorksetId v2demo -RequestId duplicateIntent -StepId stepA -Phase Apply -Status INTENT -Message 'duplicate effect' -NextBaton 'refuse' -ExpectedHead $snapshot.Head -SchemaVariant v2 -EventKind EXTERNAL_EFFECT -EffectId effect-A}catch{$refused=$true}
  Assert $refused 'terminal effect cannot be reopened'
  $refused=$false
  try{$null=New-GitLiteDleCheckpoint -RepositoryPath $root -WorksetId v2demo -RequestId v1Downgrade -StepId stepA -Phase Observe -Status OBSERVED -Message 'downgrade' -NextBaton 'refuse' -ExpectedHead $snapshot.Head}catch{$refused=$true}
  Assert $refused 'v1 downgrade after v2 denied'
  $refused=$false
  try{$null=New-GitLiteDleCheckpoint -RepositoryPath $root -WorksetId v2demo -RequestId noEvidence -StepId stepC -Phase Verify -Status VERIFIED -Message 'invented verification' -NextBaton 'refuse' -ExpectedHead $snapshot.Head -SchemaVariant v2 -EventKind EXTERNAL_EFFECT -EffectId effect-C}catch{$refused=$true}
  Assert $refused 'effect without INTENT/evidence cannot be written'
  $refused=$false
  try{$null=New-GitLiteDleCheckpoint -RepositoryPath $root -WorksetId v2demo -RequestId wrongHead -StepId stepA -Phase Plan -Status VERIFIED -Message 'stale CAS' -NextBaton 'refuse' -ExpectedHead ('a'*40) -SchemaVariant v2 -EventKind CHECKPOINT}catch{$refused=$true}
  Assert $refused 'v2 stale-parent CAS denied'
  $legacyRoot=Join-Path $env:RUNNER_TEMP 'psgitlite-v1-migration-hold'
  $null=Initialize-GitLiteDle -RepositoryPath $legacyRoot
  $v1=New-GitLiteDleCheckpoint -RepositoryPath $legacyRoot -WorksetId old -RequestId old1 -StepId base -Phase Verify -Status VERIFIED -Message 'v1 baseline' -NextBaton 'none'
  $refused=$false
  try{$null=New-GitLiteDleCheckpoint -RepositoryPath $legacyRoot -WorksetId old -RequestId migrateNoGrant -StepId migrate -Phase Apply -Status INTENT -Message 'unauthorized migration' -NextBaton 'hold' -ExpectedHead $v1.Head -SchemaVariant v2 -EventKind EXTERNAL_EFFECT -EffectId effect-new}catch{$refused=$true}
  Assert $refused 'v1 to v2 history migration requires separate admission'
  $recheck=Get-PSGitLiteDleSafeResume -RepositoryPath $root -WorksetId v2demo
  Assert ($recheck.Head -ceq $snapshot.Head -and $recheck.Verdict -ceq 'CONTINUE_FROM_BATON') 'denied writes leave previous verified DLE unchanged'
  Write-Output 'PSGITLITE_V2_STORE_NEGATIVES_PASS'
}
