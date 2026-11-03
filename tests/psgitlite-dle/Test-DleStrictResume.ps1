#requires -Version 5.1
# Synthetic contract checks: v1 decision must never suppress older pending effects.
Set-StrictMode -Version Latest
$ErrorActionPreference='Stop'
Import-Module (Join-Path $PSScriptRoot 'PSGitLiteDle.psm1') -Force
Import-Module (Join-Path $PSScriptRoot 'PSGitLiteStrictResume.psm1') -Force
function Assert([bool]$Ok,[string]$Label){if(!$Ok){throw ('FAIL '+$Label)};Write-Output ('PASS '+$Label)}
$root=Join-Path $env:RUNNER_TEMP 'psgitlite-strict-resume-fixture'
if([IO.Directory]::Exists($root)){throw 'FIXTURE_REUSE_REFUSED'}
$null=Initialize-GitLiteDle -RepositoryPath $root
$a=New-GitLiteDleCheckpoint -RepositoryPath $root -WorksetId w1 -RequestId actionA -StepId externalA -Phase Apply -Status INTENT -Message 'synthetic intent' -NextBaton 'reconcile A'
$b=New-GitLiteDleCheckpoint -RepositoryPath $root -WorksetId w1 -RequestId otherB -StepId unrelatedB -Phase Verify -Status VERIFIED -Message 'synthetic other verified' -NextBaton 'check A' -ExpectedHead $a.Head
$naive=Get-GitLiteDleSnapshot -RepositoryPath $root -WorksetId w1
Assert ($naive.Recovery -ceq 'CONTINUE_FROM_BATON') 'historical latest-status counterexample reproduced'
$safe=Get-GitLiteDleStrictResume -RepositoryPath $root -WorksetId w1
Assert ($safe.Verdict -ceq 'RECONCILE_REQUIRED' -and $safe.LegacyUncorrelated.Count -eq 1 -and !$safe.AutoReexecuteAllowed) 'earlier intent cannot be hidden by unrelated verification'
$c=New-GitLiteDleCheckpoint -RepositoryPath $root -WorksetId w2 -RequestId failedC -StepId externalC -Phase Apply -Status FAILED -Message 'synthetic failure' -NextBaton 'diagnose C'
$d=New-GitLiteDleCheckpoint -RepositoryPath $root -WorksetId w2 -RequestId passiveD -StepId unrelatedD -Phase Observe -Status OBSERVED -Message 'synthetic observation' -NextBaton 'diagnose C first' -ExpectedHead $c.Head
$safe=Get-GitLiteDleStrictResume -RepositoryPath $root -WorksetId w2
Assert ($safe.Verdict -ceq 'DIAGNOSE_FIRST_FAILURE' -and $safe.Failures.Count -eq 1) 'failure remains highest priority after newer observation'
$e=New-GitLiteDleCheckpoint -RepositoryPath $root -WorksetId w3 -RequestId doneE -StepId E -Phase Verify -Status VERIFIED -Message 'verified synthetic baseline' -NextBaton 'continue'
$safe=Get-GitLiteDleStrictResume -RepositoryPath $root -WorksetId w3
Assert ($safe.Verdict -ceq 'CONTINUE_FROM_BATON') 'unambiguous v1 verified baseline continues'
$lock=Join-Path $root '.git/refs/airea51/dle/w3.lock'
[IO.File]::WriteAllText($lock,'synthetic lock')
try{
  $safe=Get-GitLiteDleStrictResume -RepositoryPath $root -WorksetId w3
  Assert ($safe.Verdict -ceq 'RECONCILE_REQUIRED') 'unresolved lock blocks strict resume'
}finally{[IO.File]::Delete($lock)}
$null=@(& git -C $root fsck --full --no-reflogs 2>&1)
Assert ($LASTEXITCODE -eq 0) 'Git oracle validates strict resume fixture history'
Write-Output 'PSGITLITE_STRICT_RESUME_PASS'
