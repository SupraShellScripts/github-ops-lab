param([Parameter(Mandatory)][ValidateSet('prepare','resume','faults')][string]$Mode)
# Product module contains no git.exe calls. This test invokes native Git as oracle only.
Set-StrictMode -Version Latest
$ErrorActionPreference='Stop'
Import-Module (Join-Path $PSScriptRoot 'PSGitLiteDle.psm1') -Force
function Assert([bool]$Ok,[string]$Label) {
  if(-not $Ok){throw ('FAIL '+$Label)}
  Write-Output ('PASS '+$Label)
}
$root=[IO.Path]::Combine($env:RUNNER_TEMP,'psgitlite-dle-cloud-restart')
if($Mode -eq 'prepare'){
  if([IO.Directory]::Exists($root)){throw 'DLE_PREPARE_DIR_EXISTS'}
  $oldPath=$env:PATH
  try {
    $env:PATH=''
    Assert (-not (Get-Command git -ErrorAction SilentlyContinue)) 'no Git executable available'
    $init=Initialize-GitLiteDle -RepositoryPath $root
    Assert (!$init.Existing -and [IO.Directory]::Exists([IO.Path]::Combine($root,'.git'))) 'pure PowerShell repository initialization'
    $first=New-GitLiteDleCheckpoint -RepositoryPath $root -WorksetId demo -RequestId req-0001 -StepId baseline -Phase Verify -Status VERIFIED -Message 'Source baseline qualified' -NextBaton 'Plan next synthetic step'
    Assert ($first.Head -cmatch '^[0-9a-f]{40}$' -and !$first.Replay) 'initial Git commit and reference'
    $snap=Get-GitLiteDleSnapshot -RepositoryPath $root -WorksetId demo
    Assert ($snap.Head -ceq $first.Head -and $snap.Recovery -ceq 'CONTINUE_FROM_BATON') 'verified checkpoint readback'
    $replayed=New-GitLiteDleCheckpoint -RepositoryPath $root -WorksetId demo -RequestId req-0001 -StepId baseline -Phase Verify -Status VERIFIED -Message 'Source baseline qualified' -NextBaton 'Plan next synthetic step' -ExpectedHead ''
    Assert ($replayed.Replay -and $replayed.Head -ceq $first.Head) 'exact request idempotent retry after lost completion receipt'
    $refused=$false
    try{
      $null=New-GitLiteDleCheckpoint -RepositoryPath $root -WorksetId demo -RequestId req-0002 -StepId mutate -Phase Apply -Status INTENT -Message 'Synthetic operation intended' -NextBaton 'Reconcile external synthetic effect' -ExpectedHead ''
    }catch{$refused=$true}
    Assert $refused 'stale expected reference refused'
    $second=New-GitLiteDleCheckpoint -RepositoryPath $root -WorksetId demo -RequestId req-0002 -StepId mutate -Phase Apply -Status INTENT -Message 'Synthetic operation intended' -NextBaton 'Reconcile external synthetic effect' -ExpectedHead $first.Head -IntendedEffect 'write synthetic-only marker'
    Assert ($second.Parent -ceq $first.Head -and !$second.Replay) 'intent event parent ancestry'
    $current=Get-GitLiteDleSnapshot -RepositoryPath $root -WorksetId demo
    Assert ($current.Status -ceq 'INTENT' -and $current.Recovery -ceq 'RECONCILE_REQUIRED') 'pending external intent requires reconciliation'
    Assert (@(Get-GitLiteDleHistory -RepositoryPath $root -WorksetId demo).Count -eq 2) 'Git history reconstructs two DLE events'
  }finally{$env:PATH=$oldPath}
  $log=@(& git -C $root log -2 --format=%H refs/airea51/dle/demo)
  if($LASTEXITCODE -ne 0){throw 'Git log oracle failed'}
  Assert ($log.Count -eq 2 -and $log[0] -ceq $second.Head) 'native Git resolves custom DLE ref and commits'
  $null=@(& git -C $root fsck --full --no-reflogs 2>&1)
  Assert ($LASTEXITCODE -eq 0) 'native Git fsck verifies PowerShell DLE graph'
  Write-Output 'PSGITLITE_DLE_PREPARE_PASS'
}
elseif($Mode -eq 'resume'){
  Assert ([IO.Directory]::Exists($root)) 'DLE volume survives new PowerShell process'
  $before=Get-GitLiteDleSnapshot -RepositoryPath $root -WorksetId demo
  Assert ($before.Status -ceq 'INTENT' -and $before.Recovery -ceq 'RECONCILE_REQUIRED') 'fresh process refuses blind replay of ambiguous external effect'
  Assert ($before.NextBaton -ceq 'Reconcile external synthetic effect') 'next executable baton recovered'
  $event=New-GitLiteDleCheckpoint -RepositoryPath $root -WorksetId demo -RequestId req-0003 -StepId mutate -Phase Observe -Status OBSERVED -Message 'Synthetic external effect observed' -NextBaton 'Verify actual marker' -ExpectedHead $before.Head -ObservedEffect 'synthetic marker inspected'
  Assert ($event.Parent -ceq $before.Head) 'observed result persisted after restart'
  $mid=Get-GitLiteDleSnapshot -RepositoryPath $root -WorksetId demo
  Assert ($mid.Recovery -ceq 'RECONCILE_REQUIRED') 'observation is not verification'
  $final=New-GitLiteDleCheckpoint -RepositoryPath $root -WorksetId demo -RequestId req-0004 -StepId mutate -Phase Verify -Status VERIFIED -Message 'Synthetic marker verified' -NextBaton 'Continue next approved workset' -ExpectedHead $event.Head -ObservedEffect 'verified synthetic marker'
  $snap=Get-GitLiteDleSnapshot -RepositoryPath $root -WorksetId demo
  Assert ($snap.Head -ceq $final.Head -and $snap.Recovery -ceq 'CONTINUE_FROM_BATON') 'verified continuation checkpoint'
  Assert (@(Get-GitLiteDleHistory -RepositoryPath $root -WorksetId demo).Count -eq 4) 'four-event complete parent history'
  $log=@(& git -C $root log -4 --format=%H refs/airea51/dle/demo)
  if($LASTEXITCODE -ne 0){throw 'Git log oracle failed'}
  Assert ($log.Count -eq 4 -and $log[0] -ceq $final.Head) 'external Git history exact SHA parity'
  $null=@(& git -C $root fsck --full --no-reflogs 2>&1)
  Assert ($LASTEXITCODE -eq 0) 'independent Git fsck after restart'
  Write-Output 'PSGITLITE_DLE_RESUME_PASS'
}
elseif($Mode -eq 'faults'){
  $before=Get-GitLiteDleSnapshot -RepositoryPath $root -WorksetId demo
  $ref=[IO.Path]::Combine($root,'.git','refs','airea51','dle','demo')
  $lock=$ref+'.lock'
  [IO.File]::WriteAllText($lock,'synthetic stale lock')
  $refused=$false
  try{
    $null=New-GitLiteDleCheckpoint -RepositoryPath $root -WorksetId demo -RequestId req-0005 -StepId inspect -Phase Plan -Status OBSERVED -Message 'Lock test' -NextBaton 'Refuse' -ExpectedHead $before.Head
  }catch{$refused=$true}
  Assert ($refused -and [IO.File]::Exists($lock)) 'unowned existing lock never broken by agent'
  [IO.File]::Delete($lock)
  $replayRefused=$false
  try{
    $null=New-GitLiteDleCheckpoint -RepositoryPath $root -WorksetId demo -RequestId req-0002 -StepId mutate -Phase Apply -Status INTENT -Message 'Synthetic operation intended' -NextBaton 'Reconcile external synthetic effect' -ExpectedHead $before.Head -IntendedEffect 'write synthetic-only marker'
  }catch{$replayRefused=$true}
  Assert $replayRefused 'historical request ID reuse refused'
  $oid=$before.Head
  $path=[IO.Path]::Combine($root,'.git','objects',$oid.Substring(0,2),$oid.Substring(2))
  $original=[IO.File]::ReadAllBytes($path)
  try{
    $damage=New-Object byte[] $original.Length
    [Array]::Copy($original,$damage,$original.Length)
    $damage[$damage.Length-1]=[byte]($damage[$damage.Length-1] -bxor 1)
    [IO.File]::WriteAllBytes($path,$damage)
    $refused=$false
    try{$null=Get-GitLiteDleSnapshot -RepositoryPath $root -WorksetId demo}catch{$refused=$true}
    Assert $refused 'corrupted commit object refuses apparently valid DLE ref'
  }finally{[IO.File]::WriteAllBytes($path,$original)}
  $restored=Get-GitLiteDleSnapshot -RepositoryPath $root -WorksetId demo
  Assert ($restored.Head -ceq $before.Head) 'integrity recovers after restoring original bytes'
  $refused=$false
  try{
    $null=Get-GitLiteDleSnapshot -RepositoryPath $root -WorksetId '..'
  }catch{$refused=$true}
  Assert $refused 'workset path traversal refused'
  $null=@(& git -C $root fsck --full --no-reflogs 2>&1)
  Assert ($LASTEXITCODE -eq 0) 'native Git verifies post-fault state'
  Write-Output 'PSGITLITE_DLE_FAULTS_PASS'
}
