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
  $refused=$false
  try{
    $null=& $cli -RepositoryPath $repo -WorksetId '..' -Format Json
  }catch{$refused=$true}
  Assert $refused 'invalid workset rejected during observer'
  foreach($name in $writers){
    Assert ($null -eq (Get-Command -Name $name -ErrorAction SilentlyContinue)) ('no writer leaked after failed read: '+$name)
  }
  # When an embedding actor already owns the native DLE module, the observer
  # must not remove that pre-existing module during normal or failed reads.
  $modulePath=Join-Path $PSScriptRoot 'PSGitLiteDle.psm1'
  Import-Module $modulePath -Force -ErrorAction Stop
  $preloaded=Get-Module PSGitLiteDle
  Assert ($null -ne $preloaded -and
          $null -ne (Get-Command New-GitLiteDleCheckpoint -ErrorAction SilentlyContinue)) 'caller-owned DLE writer preloaded'
  $got=(& $cli -RepositoryPath $repo -WorksetId v2demo -Format Json)|ConvertFrom-Json
  Assert ($got.verdict -ceq 'CONTINUE_FROM_BATON') 'observer reads with caller-owned writer available'
  Assert ($null -ne (Get-Command New-GitLiteDleCheckpoint -ErrorAction SilentlyContinue) -and
          $null -ne (Get-Module PSGitLiteDle)) 'caller-owned writer retained after successful read'
  $refused=$false
  try{$null=& $cli -RepositoryPath $repo -WorksetId '..' -Format Json}catch{$refused=$true}
  Assert $refused 'invalid workset still rejected with caller-owned writer'
  Assert ($null -ne (Get-Command New-GitLiteDleCheckpoint -ErrorAction SilentlyContinue)) 'caller-owned writer retained after failed read'
  Remove-Module PSGitLiteDle -Force -ErrorAction Stop
  Remove-Module PSGitLiteCore -Force -ErrorAction SilentlyContinue
}finally {
  $env:PATH=$oldPath
}
Write-Output 'PSGITLITE_DLE_INSPECT_SCOPE_PASS'
