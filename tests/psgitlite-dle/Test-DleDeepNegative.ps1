#requires -Version 5.1
# Public synthetic negative fixture; always operate under RUNNER_TEMP.
Set-StrictMode -Version Latest
$ErrorActionPreference='Stop'
Import-Module (Join-Path $PSScriptRoot 'PSGitLiteDle.psm1') -Force
function Assert([bool]$ok,[string]$label){if(!$ok){throw ('FAIL '+$label)};Write-Output ('PASS '+$label)}
$repo=Join-Path $env:RUNNER_TEMP 'psgitlite-deep-ancestry-negative'
if([IO.Directory]::Exists($repo)){throw 'FIXTURE_REUSE_REFUSED'}
$null=Initialize-GitLiteDle -RepositoryPath $repo
$first=New-GitLiteDleCheckpoint -RepositoryPath $repo -WorksetId One -RequestId req01 -StepId S1 -Phase Observe -Status OBSERVED -Message 'synthetic observation' -NextBaton 'verify'
$second=New-GitLiteDleCheckpoint -RepositoryPath $repo -WorksetId One -RequestId req02 -StepId S1 -Phase Verify -Status VERIFIED -Message 'synthetic verification' -NextBaton 'continue' -ExpectedHead $first.Head
$caseRefused=$false
try{$null=Get-GitLiteDleSnapshot -RepositoryPath $repo -WorksetId one}catch{$caseRefused=$true}
Assert $caseRefused 'case-folded workset alias rejected'
$refLock=Join-Path $repo '.git/refs/airea51/dle/One.lock'
[IO.File]::WriteAllText($refLock,'synthetic lock fixture')
try {
  $snapshot=Get-GitLiteDleSnapshot -RepositoryPath $repo -WorksetId One
  Assert ($snapshot.Recovery -ceq 'LOCK_RECONCILE_REQUIRED') 'stale lock blocks automatic resume'
}finally{[IO.File]::Delete($refLock)}
$parentObject=Join-Path (Join-Path (Join-Path $repo '.git/objects') $first.Head.Substring(0,2)) $first.Head.Substring(2)
$original=[IO.File]::ReadAllBytes($parentObject)
try {
  $damage=New-Object byte[] $original.Length
  [Array]::Copy($original,$damage,$original.Length)
  $damage[$damage.Length-1]=[byte]($damage[$damage.Length-1] -bxor 1)
  [IO.File]::WriteAllBytes($parentObject,$damage)
  $refused=$false
  try{$null=Get-GitLiteDleSnapshot -RepositoryPath $repo -WorksetId One}catch{$refused=$true}
  Assert $refused 'valid head cannot conceal corrupt first commit'
}finally{[IO.File]::WriteAllBytes($parentObject,$original)}
Assert ((Get-GitLiteDleSnapshot -RepositoryPath $repo -WorksetId One).Head -ceq $second.Head) 'restored ancestry accepted'
$null=@(& git -C $repo fsck --full --no-reflogs 2>&1)
Assert ($LASTEXITCODE -eq 0) 'independent Git fsck passes after restoration'
Write-Output 'PSGITLITE_P0_DEEP_NEGATIVES_PASS'
