# Public-safe three-audience command facade smoke (no executable Git on PATH).
Set-StrictMode -Version Latest
$ErrorActionPreference='Stop'
function Assert([bool]$Ok,[string]$Label){
  if(-not $Ok){throw ('FAIL '+$Label)}
  Write-Output ('PASS '+$Label)
}
$root=[IO.Path]::Combine($env:RUNNER_TEMP,'psgitlite-dle-cloud-restart')
$cli=Join-Path $PSScriptRoot 'Invoke-GitLiteDle.ps1'
$oldPath=$env:PATH
try{
  $env:PATH=''
  Assert (-not (Get-Command git -ErrorAction SilentlyContinue)) 'CLI Git executable unavailable'
  $json=& $cli -Command Inspect -RepositoryPath $root -WorksetId demo -OutputFormat Json
  $item=$json | ConvertFrom-Json
  Assert ($item.Status -ceq 'VERIFIED' -and $item.Recovery -ceq 'CONTINUE_FROM_BATON') 'agent JSON inspect'
  $lines=@(& $cli -Command History -RepositoryPath $root -WorksetId demo -OutputFormat Jsonl)
  Assert ($lines.Count -eq 4) 'automation JSONL history record count'
  $human=@(& $cli -Command Inspect -RepositoryPath $root -WorksetId demo -OutputFormat Human)
  Assert ($human.Count -ge 2 -and $human[0] -match 'workset=demo' -and $human[1] -match 'Next baton') 'human readable inspect with baton'
  $digest=('a'*64)
  $written=& $cli -Command Checkpoint -RepositoryPath $root -WorksetId demo -RequestId req-0006 -StepId followup -Phase Reconcile -Status VERIFIED -Message 'Durable synthetic handoff acceptance' -NextBaton 'Cold-start next assigned workcell' -ExpectedHead $item.Head -ApprovalRef 'external-synthetic-grant-only' -SourceRootDigest $digest -EvidenceRefs @('fixture:synthetic','git:oracle') -OutputFormat Json
  $result=$written | ConvertFrom-Json
  Assert ($result.Head -cmatch '^[a-f0-9]{40}$') 'CLI writes canonical Git checkpoint'
  $after=(& $cli -Command Inspect -RepositoryPath $root -WorksetId demo -OutputFormat Json) | ConvertFrom-Json
  Assert ($after.Event.approvalRef -ceq 'external-synthetic-grant-only' -and $after.Event.sourceRootDigest -ceq $digest -and $after.Event.evidenceRefs.Count -eq 2) 'typed provenance and independent approval references survive'
  $replay=(& $cli -Command Checkpoint -RepositoryPath $root -WorksetId demo -RequestId req-0006 -StepId followup -Phase Reconcile -Status VERIFIED -Message 'Durable synthetic handoff acceptance' -NextBaton 'Cold-start next assigned workcell' -ExpectedHead $item.Head -ApprovalRef 'external-synthetic-grant-only' -SourceRootDigest $digest -EvidenceRefs @('fixture:synthetic','git:oracle') -OutputFormat Json) | ConvertFrom-Json
  Assert ($replay.Replay -and $replay.Head -ceq $result.Head) 'automation idempotency over CLI'
}finally{$env:PATH=$oldPath}
$null=@(& git -C $root fsck --full --no-reflogs 2>&1)
Assert ($LASTEXITCODE -eq 0) 'CLI DLE history compatible with independent Git'
Write-Output 'PSGITLITE_DLE_THREE_AUDIENCE_PASS'
