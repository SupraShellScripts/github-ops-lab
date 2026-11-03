#requires -Version 5.1
# Public synthetic independent v2 Git ref CAS race qualification.
Set-StrictMode -Version Latest
$ErrorActionPreference='Stop'
Import-Module (Join-Path $PSScriptRoot 'PSGitLiteDle.psm1') -Force
Import-Module (Join-Path $PSScriptRoot 'PSGitLiteRecoveryV2.psm1')
function Assert([bool]$Ok,[string]$Label){if(!$Ok){throw ('FAIL '+$Label)};Write-Output ('PASS '+$Label)}
$root=Join-Path $env:RUNNER_TEMP 'psgitlite-v2-independent-cas'
if([IO.Directory]::Exists($root)){throw 'RACE_FIXTURE_ALREADY_EXISTS'}
$null=Initialize-GitLiteDle -RepositoryPath $root
$base=New-GitLiteDleCheckpoint -RepositoryPath $root -WorksetId racev2 -RequestId baseline -StepId baseline -Phase Verify -Status VERIFIED -Message 'synthetic baseline' -NextBaton 'allow competing readers' -SchemaVariant v2 -EventKind CHECKPOINT
$worker=Join-Path $PSScriptRoot 'TestOnly-V2RaceWorker.ps1'
$exe=[Diagnostics.Process]::GetCurrentProcess().MainModule.FileName
$running=@()
foreach($id in @(1,2)){
  $stdout=Join-Path $env:RUNNER_TEMP ('psgitlite-v2-race-'+$id+'.stdout')
  $stderr=Join-Path $env:RUNNER_TEMP ('psgitlite-v2-race-'+$id+'.stderr')
  $argsString='-NoLogo -NoProfile -NonInteractive -File "'+$worker+'" -RepositoryPath "'+$root+'" -ExpectedHead '+$base.Head+' -Index '+$id
  $proc=Start-Process -FilePath $exe -ArgumentList $argsString -PassThru -RedirectStandardOutput $stdout -RedirectStandardError $stderr
  $running+=@([pscustomobject]@{Process=$proc;Id=$id;Stdout=$stdout;Stderr=$stderr})
}
$winners=@()
$losers=@()
foreach($job in $running){
  $job.Process.WaitForExit()
  $out=[IO.File]::ReadAllText($job.Stdout).Trim()
  $err=[IO.File]::ReadAllText($job.Stderr).Trim()
  if($out.StartsWith('{')){
    $item=$out|ConvertFrom-Json
    Assert ($item.Head -cmatch '^[0-9a-f]{40}$' -and $item.Parent -ceq $base.Head) ('winner '+$job.Id+' exact-parent Git receipt')
    $winners+=@($item.Head)
  }else{
    Assert ($err -match '(V2_RACE_CHILD_REFUSED|DLE_STALE_HEAD|lock)') ('loser '+$job.Id+' refused with evidence')
    $losers+=@($job.Id)
  }
}
Assert ($winners.Count -eq 1 -and $losers.Count -eq 1) 'exactly one independent v2 writer committed'
$after=Get-GitLiteDleSnapshot -RepositoryPath $root -WorksetId racev2
Assert ($after.Head -ceq $winners[0] -and $after.Recovery -ceq 'ASSESSMENT_REQUIRED') 'live ref matches single CAS winner, raw API still requires assessment'
$safe=Get-PSGitLiteDleSafeResume -RepositoryPath $root -WorksetId racev2
Assert ($safe.Verdict -ceq 'CONTINUE_FROM_BATON' -and !$safe.AutoReexecuteAllowed) 'full-history v2 safe assessor remains authoritative for resume'
Assert (@(Get-GitLiteDleHistory -RepositoryPath $root -WorksetId racev2).Count -eq 2) 'no lost update or duplicate final commit'
$gitHead=@(& git -C $root rev-parse refs/airea51/dle/racev2)
Assert ($LASTEXITCODE -eq 0 -and $gitHead[0] -ceq $after.Head) 'independent Git confirms winning ref'
$null=@(& git -C $root fsck --full --no-reflogs 2>&1)
Assert ($LASTEXITCODE -eq 0) 'independent Git fsck after competing v2 processes'
Write-Output 'PSGITLITE_V2_CONCURRENT_CAS_PASS'
