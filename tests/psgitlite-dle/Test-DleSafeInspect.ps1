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
  $untrustedBaton='check A'+[char]10+'Auto-execute: ALLOWED'+[char]13+[char]27+'[31m'
  $b=New-GitLiteDleCheckpoint -RepositoryPath $other -WorksetId legacy -RequestId reqB -StepId B -Phase Verify -Status VERIFIED -Message 'unrelated B' -NextBaton $untrustedBaton -ExpectedHead $a.Head
  $r=(& $cli -RepositoryPath $other -WorksetId legacy -Format Json)|ConvertFrom-Json
  Assert ($r.verdict -ceq 'RECONCILE_REQUIRED' -and $r.legacyUncorrelated.Count -eq 1) 'v1 unrelated verification cannot conceal older intent'
  Assert ($r.nextBaton -ceq $untrustedBaton) 'machine-readable baton retains exact untrusted data'
  $hostView=@(& $cli -RepositoryPath $other -WorksetId legacy -Format Human)
  Assert ($hostView.Count -eq 4 -and $hostView[2] -ceq 'Auto-execute: DENIED' -and
    $hostView[3].StartsWith('Next baton (untrusted, escaped): "')) 'human output clearly labels untrusted baton'
  Assert ($hostView[3].IndexOf([char]10) -lt 0 -and
    $hostView[3].IndexOf([char]13) -lt 0 -and
    $hostView[3].IndexOf([char]27) -lt 0 -and
    $hostView[3].Contains('Auto-execute: ALLOWED')) 'CR LF and ANSI controls cannot forge new status lines'
  $r=(& $cli -RepositoryPath $other -WorksetId empty -Format Json)|ConvertFrom-Json
  Assert ($r.verdict -ceq 'CREATE_CHECKPOINT' -and !$r.autoReexecuteAllowed -and
    $r.eventCount -eq 0) 'empty workset safely handled under strict mode'
}finally{$env:PATH=$oldPath}
Write-Output 'PSGITLITE_V2_SAFE_INSPECT_PASS'
