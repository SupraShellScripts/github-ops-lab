#requires -Version 5.1
# Native qualification: read-only DLE inspection must not publish writer
# commands into the calling automation/agent PowerShell session.
Set-StrictMode -Version Latest
$ErrorActionPreference='Stop'
function Assert([bool]$Ok,[string]$Label) {
  if(-not $Ok){throw ('FAIL '+$Label)}
  Write-Output ('PASS '+$Label)
}
$cli=Join-Path $PSScriptRoot 'Invoke-DleSafeInspect.ps1'
# This synthetic workset is created by Test-DleV2Store.ps1 prepare/resume
# in earlier steps of the same runner job; every step uses a fresh shell.
$repo=Join-Path $env:RUNNER_TEMP 'psgitlite-v2-store-restart'
if(-not [IO.Directory]::Exists((Join-Path $repo '.git'))){
  throw 'DLE_SCOPE_FIXTURE_NOT_PREPARED'
}
$writers=@('Initialize-GitLiteDle','New-GitLiteDleCheckpoint',
           'New-GitLiteRepository','New-GitLiteObject')
foreach($name in $writers){
  Assert ($null -eq (Get-Command -Name $name -ErrorAction SilentlyContinue)) ('no preexisting writer: '+$name)
}
$oldPath=$env:PATH
try {
  $env:PATH=''
  $raw=& $cli -RepositoryPath $repo -WorksetId v2demo -Format Json
  $result=$raw | ConvertFrom-Json
  Assert ($result.verdict -ceq 'CONTINUE_FROM_BATON' -and
          $result.authority -ceq 'OBSERVATION_ONLY' -and
          !$result.autoReexecuteAllowed) 'observer reads verified synthetic state without granting execution'
  $human=@(& $cli -RepositoryPath $repo -WorksetId v2demo -Format Human)
  Assert ($human.Count -ge 3 -and $human[2] -ceq 'Auto-execute: DENIED') 'human view denies execution'
  foreach($name in $writers){
    Assert ($null -eq (Get-Command -Name $name -ErrorAction SilentlyContinue)) ('no writer leaked to caller: '+$name)
  }
}finally {
  $env:PATH=$oldPath
}
Write-Output 'PSGITLITE_DLE_INSPECT_SCOPE_PASS'
