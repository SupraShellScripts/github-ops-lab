#requires -Version 5.1
# Public synthetic v1 compatibility / safe resume; no private source.
Set-StrictMode -Version Latest
$ErrorActionPreference='Stop'
Import-Module (Join-Path $PSScriptRoot 'PSGitLiteDle.psm1') -Force
Import-Module (Join-Path $PSScriptRoot 'PSGitLiteRecoveryV2.psm1')
function Assert([bool]$Ok,[string]$Label){if(!$Ok){throw ('FAIL '+$Label)};Write-Output ('PASS '+$Label)}
$root=Join-Path $env:RUNNER_TEMP 'psgitlite-v2-legacy-interop'
if([IO.Directory]::Exists($root)){throw 'FIXTURE_ALREADY_EXISTS'}
$null=Initialize-GitLiteDle -RepositoryPath $root
$a=New-GitLiteDleCheckpoint -RepositoryPath $root -WorksetId w1 -RequestId intentA -StepId A -Phase Apply -Status INTENT -Message 'synthetic external A' -NextBaton 'reconcile A'
$b=New-GitLiteDleCheckpoint -RepositoryPath $root -WorksetId w1 -RequestId unrelatedB -StepId B -Phase Verify -Status VERIFIED -Message 'unrelated verification' -NextBaton 'check A' -ExpectedHead $a.Head
$naive=Get-GitLiteDleSnapshot -RepositoryPath $root -WorksetId w1
Assert ($naive.Recovery -ceq 'CONTINUE_FROM_BATON') 'legacy last-status counterexample reproduced'
$safe=Get-PSGitLiteDleSafeResume -RepositoryPath $root -WorksetId w1
Assert ($safe.Verdict -ceq 'RECONCILE_REQUIRED' -and $safe.Assessment.LegacyUncorrelated.Count -eq 1 -and !$safe.AutoReexecuteAllowed) 'v2 assessor refuses uncorrelated v1 intent'
$lock=Join-Path $root '.git/refs/airea51/dle/w1.lock'
[IO.File]::WriteAllText($lock,'test-only')
try {
  $safe=Get-PSGitLiteDleSafeResume -RepositoryPath $root -WorksetId w1
  Assert ($safe.Verdict -ceq 'RECONCILE_REQUIRED') 'stale lock never yields automatic continuation'
}finally{[IO.File]::Delete($lock)}
$null=@(& git -C $root fsck --full --no-reflogs 2>&1)
Assert ($LASTEXITCODE -eq 0) 'native Git independently validates legacy DLE ancestry'
Write-Output 'PSGITLITE_RECOVERY_V2_LEGACY_PASS'
