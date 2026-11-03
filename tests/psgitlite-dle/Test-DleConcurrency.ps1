# Synthetic actual multi-process CAS test; external process launcher belongs to
# qualification harness ONLY, never to PSGitLite product runtime.
Set-StrictMode -Version Latest
$ErrorActionPreference='Stop'
Import-Module (Join-Path $PSScriptRoot 'PSGitLiteDle.psm1') -Force
function Assert([bool]$Ok,[string]$Label){
  if(!$Ok){throw ('FAIL '+$Label)}
  Write-Output ('PASS '+$Label)
}
$root=[IO.Path]::Combine($env:RUNNER_TEMP,'psgitlite-dle-cloud-restart')
$before=Get-GitLiteDleSnapshot -RepositoryPath $root -WorksetId demo
$exe=[Diagnostics.Process]::GetCurrentProcess().MainModule.FileName
$cli=Join-Path $PSScriptRoot 'Invoke-GitLiteDle.ps1'
$jobs=@()
foreach($i in @(1,2)){
  $stdout=Join-Path $env:RUNNER_TEMP ('dle-race-'+$i+'.out')
  $stderr=Join-Path $env:RUNNER_TEMP ('dle-race-'+$i+'.err')
  $argsList=@('-NoLogo','-NoProfile','-NonInteractive','-File',$cli,
    '-Command','Checkpoint','-RepositoryPath',$root,
    '-WorksetId','demo','-RequestId',('race-0'+$i),'-StepId','race',
    '-Phase','Plan','-Status','VERIFIED','-Message',('racing-writer-'+$i),
    '-NextBaton','Inspect winner', '-ExpectedHead',$before.Head,
    '-OutputFormat','Json')
  $started=Start-Process -FilePath $exe -ArgumentList $argsList -PassThru -RedirectStandardOutput $stdout -RedirectStandardError $stderr
  $jobs+=@([pscustomobject]@{Process=$started;Stdout=$stdout;Stderr=$stderr;Id=$i})
}
$success=0
$winner=$null
foreach($entry in $jobs){
  $entry.Process.WaitForExit()
  $code=$entry.Process.ExitCode
  if($code -eq 0){
    $success++
    $winner=([IO.File]::ReadAllText($entry.Stdout)|ConvertFrom-Json).Head
  }else{
    $errorText=[IO.File]::ReadAllText($entry.Stderr)
    Assert ($errorText -match '(DLE_STALE_HEAD|lock|DLE_OPERATION_FAILED)') ('loser '+$entry.Id+' failed for expected race/lock reason')
  }
}
Assert ($success -eq 1) 'exactly one writer wins stale-parent CAS race'
$after=Get-GitLiteDleSnapshot -RepositoryPath $root -WorksetId demo
Assert ($after.Head -ceq $winner -and $after.Parent -ceq $before.Head) 'winning writer commit is exact observed ref head'
$log=@(& git -C $root log -1 --format=%H refs/airea51/dle/demo)
if($LASTEXITCODE -ne 0){throw 'Git log oracle failed'}
Assert ($log[0] -ceq $after.Head) 'Git oracle sees same winning CAS result'
$null=@(& git -C $root fsck --full --no-reflogs 2>&1)
Assert ($LASTEXITCODE -eq 0) 'race leaves valid Git repository'
Write-Output 'PSGITLITE_DLE_CONCURRENT_WRITERS_PASS'
