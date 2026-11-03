param([Parameter(Mandatory)][ValidateSet('interrupt','recover')][string]$Mode)
# Public synthetic process-loss-after-ref-promotion test; fixture only.
Set-StrictMode -Version Latest
$ErrorActionPreference='Stop'
function Assert([bool]$Ok,[string]$Label){if(!$Ok){throw ('FAIL '+$Label)};Write-Output ('PASS '+$Label)}
$root=Join-Path $env:RUNNER_TEMP 'psgitlite-postref-crash-fixture'
$marker=Join-Path $root 'synthetic-request.txt'
$sentinel=Join-Path $root 'unexpected-return.txt'
$source=Join-Path $PSScriptRoot 'PSGitLiteDle.psm1'
$instrumented=Join-Path $PSScriptRoot 'PSGitLiteDle.TestOnlyPostRef.psm1'
$workset='postref'
$request='postref-req01'
$step='synthetic-effect'
$message='Intended synthetic external action not executed'
$baton='Reconcile external synthetic effect before continuing'
if($Mode -eq 'interrupt'){
  if([IO.Directory]::Exists($root)){throw 'REUSED_CRASH_FIXTURE'}
  Import-Module $source -Force
  $null=Initialize-GitLiteDle -RepositoryPath $root
  [IO.File]::WriteAllText($marker,$request,[Text.Encoding]::ASCII)
  $bytes=[IO.File]::ReadAllText($source)
  $needle='}else{[IO.File]::Move($lock,$ref)}'
  $count=($bytes.Split([string[]]@($needle),[StringSplitOptions]::None).Length-1)
  if($count -ne 1){throw 'INJECTION_POINT_MISSING'}
  $patch=$needle+[Environment]::NewLine+'    [Diagnostics.Process]::GetCurrentProcess().Kill()'
  $new=$bytes.Replace($needle,$patch)
  [IO.File]::WriteAllText($instrumented,$new,[Text.UTF8Encoding]::new($false))
  Import-Module $instrumented -Force
  $null=New-GitLiteDleCheckpoint -RepositoryPath $root -WorksetId $workset -RequestId $request -StepId $step -Phase Apply -Status INTENT -Message $message -NextBaton $baton -IntendedEffect 'synthetic fixture only'
  [IO.File]::WriteAllText($sentinel,'unexpected successful return')
  throw 'POSTREF_KILL_DID_NOT_HAPPEN'
}
else{
  Import-Module $source -Force
  Assert ([IO.File]::Exists($marker)) 'original request persisted before process death'
  Assert (-not [IO.File]::Exists($sentinel)) 'writer did not return completion receipt'
  $current=Get-GitLiteDleSnapshot -RepositoryPath $root -WorksetId $workset
  Assert ($current.Head -cmatch '^[a-f0-9]{40}$' -and $current.Status -ceq 'INTENT' -and $current.Recovery -ceq 'RECONCILE_REQUIRED') 'committed ref survives process death but action remains uncertain'
  $lock=Join-Path $root '.git/refs/airea51/dle/postref.lock'
  Assert (-not [IO.File]::Exists($lock)) 'ref already promoted; no stale lock'
  $retry=New-GitLiteDleCheckpoint -RepositoryPath $root -WorksetId $workset -RequestId $request -StepId $step -Phase Apply -Status INTENT -Message $message -NextBaton $baton -IntendedEffect 'synthetic fixture only'
  Assert ($retry.Replay -and $retry.Head -ceq $current.Head) 'lost acknowledgement is idempotently recovered without duplicate write'
  Assert (@(Get-GitLiteDleHistory -RepositoryPath $root -WorksetId $workset).Count -eq 1) 'no duplicate commit after retry'
  $oid=@(& git -C $root rev-parse refs/airea51/dle/postref)
  Assert ($LASTEXITCODE -eq 0 -and $oid[0] -ceq $current.Head) 'native Git sees committed ref'
  $null=@(& git -C $root fsck --full --no-reflogs 2>&1)
  Assert ($LASTEXITCODE -eq 0) 'native Git validates post-ref hard-kill repository'
  Write-Output 'PSGITLITE_POSTREF_HARDKILL_RECOVERY_PASS'
}
