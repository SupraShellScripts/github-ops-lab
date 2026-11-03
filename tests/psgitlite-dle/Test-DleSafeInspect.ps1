#requires -Version 5.1
# Public synthetic three-audience read-only safe inspect qualification.
Set-StrictMode -Version Latest
$ErrorActionPreference='Stop'
Import-Module (Join-Path $PSScriptRoot 'PSGitLiteDle.psm1') -Force
function Assert([bool]$Ok,[string]$Label){
  if(!$Ok){throw ('FAIL '+$Label)}
  Write-Output ('PASS '+$Label)
}
$cli=Join-Path $PSScriptRoot 'Invoke-DleSafeInspect.ps1'
$root=Join-Path $env:RUNNER_TEMP 'psgitlite-v2-store-restart'
$oldPath=$env:PATH
try{
  $env:PATH=''
  $json=& $cli -RepositoryPath $root -WorksetId v2demo -Format Json
  $item=$json|ConvertFrom-Json
  Assert ($item.schemaVersion -ceq 'psgitlite.dle-safe-inspect.v1' -and
    $item.verdict -ceq 'CONTINUE_FROM_BATON' -and !$item.autoReexecuteAllowed) 'agent typed full-history verdict'
  Assert ($item.eventCount -eq 4 -and $item.pendingEffects.Count -eq 0 -and
    $item.authority -ceq 'OBSERVATION_ONLY') 'v2 verified effects and no implicit authority'
  $jsonl=@(& $cli -RepositoryPath $root -WorksetId v2demo -Format Jsonl)
  Assert ($jsonl.Count -eq 1 -and ($jsonl[0]|ConvertFrom-Json).head -ceq $item.head) 'automation JSONL stable read-only receipt'
  $human=@(& $cli -RepositoryPath $root -WorksetId v2demo -Format Human)
  Assert ($human.Count -ge 3 -and $human[0] -match 'verdict=CONTINUE_FROM_BATON' -and
    $human[2] -match 'Auto-execute: DENIED') 'human verdict never authorizes external execution'
  $other=Join-Path $env:RUNNER_TEMP 'psgitlite-safe-inspect-v1-legacy'
  $null=Initialize-GitLiteDle -RepositoryPath $other
  $a=New-GitLiteDleCheckpoint -RepositoryPath $other -WorksetId legacy -RequestId reqA -StepId A -Phase Apply -Status INTENT -Message 'legacy synthetic A' -NextBaton 'reconcile A'
  $b=New-GitLiteDleCheckpoint -RepositoryPath $other -WorksetId legacy -RequestId reqB -StepId B -Phase Verify -Status VERIFIED -Message 'unrelated B' -NextBaton 'check A' -ExpectedHead $a.Head
  $r=(& $cli -RepositoryPath $other -WorksetId legacy -Format Json)|ConvertFrom-Json
  Assert ($r.verdict -ceq 'RECONCILE_REQUIRED' -and $r.legacyUncorrelated.Count -eq 1) 'v1 unrelated verification cannot conceal older intent'
  $r=(& $cli -RepositoryPath $other -WorksetId empty -Format Json)|ConvertFrom-Json
  Assert ($r.verdict -ceq 'CREATE_CHECKPOINT' -and !$r.autoReexecuteAllowed -and
    $r.eventCount -eq 0) 'empty workset safely handled under strict mode'
}finally{$env:PATH=$oldPath}
Write-Output 'PSGITLITE_V2_SAFE_INSPECT_PASS'
