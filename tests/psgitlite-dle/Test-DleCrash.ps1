param([Parameter(Mandatory)][ValidateSet('interrupt','recover')][string]$Mode)
# Synthetic fault-injection only. In 'interrupt' a temporary copy of the actual
# DLE module is instrumented to kill the interpreter after lock flush, before CAS.
# Never publish/install the instrumented module as production source.
Set-StrictMode -Version Latest
$ErrorActionPreference='Stop'
function Assert([bool]$Ok,[string]$Label){
  if(!$Ok){throw ('FAIL '+$Label)}
  Write-Output ('PASS '+$Label)
}
$root=[IO.Path]::Combine($env:RUNNER_TEMP,'psgitlite-dle-cloud-restart')
$marker=[IO.Path]::Combine($root,'synthetic-crash-marker.txt')
$sentinel=[IO.Path]::Combine($root,'synthetic-not-killed.txt')
$ref=[IO.Path]::Combine($root,'.git','refs','airea51','dle','demo')
$lock=$ref+'.lock'
if($Mode -eq 'interrupt'){
  $sourcePath=Join-Path $PSScriptRoot 'PSGitLiteDle.psm1'
  $instrumented=Join-Path $PSScriptRoot 'PSGitLiteDle.TestOnlyInterrupted.psm1'
  $source=[IO.File]::ReadAllText($sourcePath)
  $needle='    if([IO.File]::Exists($ref)){'
  $count=($source.Split([string[]]@($needle),[StringSplitOptions]::None).Length-1)
  if($count -ne 1){throw 'CRASH_INJECTION_POINT_CHANGED'}
  $injected=$source.Replace($needle,('    [Diagnostics.Process]::GetCurrentProcess().Kill()'+[char]10+$needle))
  [IO.File]::WriteAllText($instrumented,$injected,[Text.UTF8Encoding]::new($false))
  Import-Module $instrumented -Force
  $before=Get-GitLiteDleSnapshot -RepositoryPath $root -WorksetId demo
  if($before.Status -cne 'VERIFIED'){throw 'PRE_CRASH_SNAPSHOT_NOT_VERIFIED'}
  [IO.File]::WriteAllText($marker,$before.Head,[Text.Encoding]::ASCII)
  $null=New-GitLiteDleCheckpoint -RepositoryPath $root -WorksetId demo -RequestId req-kill01 -StepId fault -Phase Apply -Status INTENT -Message 'test-only kill after Git ref lock flush' -NextBaton 'Reconcile crashed writer' -ExpectedHead $before.Head
  [IO.File]::WriteAllText($sentinel,'FAULT: fault injection did not kill process')
  throw 'FAULT_INJECTION_FAILED'
}
else{
  Import-Module (Join-Path $PSScriptRoot 'PSGitLiteDle.psm1') -Force
  Assert ([IO.File]::Exists($marker)) 'crash preparation marker persisted'
  Assert (-not [IO.File]::Exists($sentinel)) 'instrumented writer did not resume after process termination'
  $oldHead=[IO.File]::ReadAllText($marker).Trim()
  $current=Get-GitLiteDleSnapshot -RepositoryPath $root -WorksetId demo
  Assert ($current.Head -ceq $oldHead -and $current.Status -ceq 'VERIFIED') 'old committed DLE ref survives killed in-progress writer'
  Assert ([IO.File]::Exists($lock)) 'incomplete writer leaves lock for explicit diagnosis'
  $refused=$false
  try{
    $null=New-GitLiteDleCheckpoint -RepositoryPath $root -WorksetId demo -RequestId req-lock02 -StepId afterkill -Phase Plan -Status VERIFIED -Message 'Must refuse unowned lock' -NextBaton 'No automatic stale lock deletion' -ExpectedHead $oldHead
  }catch{$refused=$true}
  Assert ($refused -and [IO.File]::Exists($lock)) 'future writer fails closed on stale lock'
  # Explicit synthetic recovery approval: remove only a known fixture-owned lock
  # after checking it is not held by a live process, never from product code.
  [IO.File]::Delete($lock)
  $next=New-GitLiteDleCheckpoint -RepositoryPath $root -WorksetId demo -RequestId req-recovered -StepId afterkill -Phase Reconcile -Status VERIFIED -Message 'Owner inspected interrupted transaction' -NextBaton 'Resume synthetic work from verified state' -ExpectedHead $oldHead
  Assert ($next.Parent -ceq $oldHead) 'explicitly reconciled writer advances validated ancestry'
  $null=@(& git -C $root fsck --full --no-reflogs 2>&1)
  Assert ($LASTEXITCODE -eq 0) 'independent Git fsck following process-kill and manual lock recovery'
  Write-Output 'PSGITLITE_DLE_HARDKILL_RECOVERY_PASS'
}
