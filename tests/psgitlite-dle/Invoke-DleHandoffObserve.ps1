param(
  [Parameter(Mandatory)][string]$ProjectRoot,
  [Parameter(Mandatory)][string]$RepositoryPath,
  [AllowEmptyString()][string]$ExpectedHead='',
  [ValidateSet('Human','Json')][string]$OutputFormat='Json'
)
# PUBLIC-ORIGINAL OBSERVER: reads AIrea51 handoff pointer, records ONLY its
# digest and minimal resume instruction. Never modifies agent-exchange/current.json.
# No model execution, no approval, no network, no Git executable.
Set-StrictMode -Version Latest
$ErrorActionPreference='Stop'
Import-Module (Join-Path $PSScriptRoot 'PSGitLiteDle.psm1') -Force
function Assert-RelativeHandoff([string]$Path){
  if([string]::IsNullOrWhiteSpace($Path) -or $Path.Length -gt 240 -or
     $Path -cnotmatch '^[A-Za-z0-9_./-]+$' -or $Path.Contains('..') -or
     $Path.Contains('//') -or $Path.StartsWith('/') -or $Path.EndsWith('/')){
    throw 'DLE_UNSAFE_HANDOFF_PATH'
  }
}
$project=[IO.Path]::GetFullPath($ProjectRoot)
$handoff=[IO.Path]::Combine($project,'agent-exchange','current.json')
foreach($path in @($project,[IO.Path]::Combine($project,'agent-exchange'),$handoff)){
  if([IO.File]::Exists($path) -or [IO.Directory]::Exists($path)){
    if(([IO.File]::GetAttributes($path) -band [IO.FileAttributes]::ReparsePoint) -ne 0){
      throw 'DLE_HANDOFF_REPARSE_REFUSED'
    }
  }
}
if(-not [IO.File]::Exists($handoff)){throw 'DLE_HANDOFF_NOT_FOUND'}
$info=[IO.FileInfo]::new($handoff)
if($info.Length -gt 262144){throw 'DLE_HANDOFF_SIZE_LIMIT'}
$bytes=[IO.File]::ReadAllBytes($handoff)
$text=[Text.UTF8Encoding]::new($false,$true).GetString($bytes)
$doc=$text | ConvertFrom-Json
if($doc.schemaVersion -cne '1.0' -or $doc.repository -cne 'SupraShellScripts/AIrea51' -or
   [string]::IsNullOrWhiteSpace($doc.handoffId)){throw 'DLE_HANDOFF_SCHEMA_OR_REPO'}
Assert-RelativeHandoff $doc.promptPath
if($doc.priorReportPath){Assert-RelativeHandoff $doc.priorReportPath}
if($doc.promptPath -cnotmatch '^agent-exchange/prompts/' -or
   ($doc.priorReportPath -and $doc.priorReportPath -cnotmatch '^agent-exchange/reports/')){
  throw 'DLE_HANDOFF_PATH_SCOPE'
}
$hasher=[Security.Cryptography.SHA256]::Create()
try{$sha=([BitConverter]::ToString($hasher.ComputeHash($bytes))).Replace('-','').ToLowerInvariant()}
finally{$hasher.Dispose()}
$id=$doc.handoffId
$requestId='handoff-'+$sha.Substring(0,20)
$baton='Read AGENTS.md and continue the current AIrea51 handoff; verify current.json digest'
$evidence=[string[]]@(('sha256:'+$sha),'local:agent-exchange/current.json')
$result=New-GitLiteDleCheckpoint -RepositoryPath $RepositoryPath -WorksetId $id -RequestId $requestId -StepId handoff-observe -Phase Observe -Status OBSERVED -Message ('Observed AIrea51 handoff pointer '+$id) -NextBaton $baton -ExpectedHead $ExpectedHead -ObservedEffect 'Handoff pointer read; verification/approval not inferred' -Actor handoff-observer -EvidenceRefs $evidence
if($OutputFormat -eq 'Json'){
  Write-Output (ConvertTo-Json -InputObject ([ordered]@{handoffId=$id;handoffDigestSha256=$sha;
    head=$result.Head;replay=$result.Replay;status='OBSERVED';authority='OBSERVED_NOT_AUTHENTICATED';nextBaton=$baton}) -Depth 5 -Compress)
}else{
  Write-Output ('DLE observed handoff '+$id+' sha256='+$sha+' GitCommit='+$result.Head+' replay='+$result.Replay)
  Write-Output ('Next baton: '+$baton)
}
