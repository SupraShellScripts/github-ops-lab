# Public-original synthetic AIrea51 handoff-pointer DLE ingestion test.
Set-StrictMode -Version Latest
$ErrorActionPreference='Stop'
Import-Module (Join-Path $PSScriptRoot 'PSGitLiteDle.psm1') -Force
function Assert([bool]$Ok,[string]$Label){
  if(!$Ok){throw ('FAIL '+$Label)}
  Write-Output ('PASS '+$Label)
}
$root=[IO.Path]::Combine($env:RUNNER_TEMP,'psgitlite-dle-handoff')
$project=[IO.Path]::Combine($root,'synthetic-ai51')
$repo=[IO.Path]::Combine($root,'dle-store')
$dir=[IO.Path]::Combine($project,'agent-exchange')
[void][IO.Directory]::CreateDirectory($dir)
$pointer=[IO.Path]::Combine($dir,'current.json')
$doc=[ordered]@{schemaVersion='1.0';project='AIrea51';repository='SupraShellScripts/AIrea51';
  handoffId='AIREA51-SYNTHETIC-1';status='ready';promptPath='agent-exchange/prompts/synthetic.md';
  priorReportPath='agent-exchange/reports/synthetic.md';nextActions=@('SECRET_MARKER_DO_NOT_EXPORT')}
[IO.File]::WriteAllText($pointer,(ConvertTo-Json -InputObject $doc -Depth 6 -Compress),[Text.UTF8Encoding]::new($false))
$null=Initialize-GitLiteDle -RepositoryPath $repo
$observer=Join-Path $PSScriptRoot 'Invoke-DleHandoffObserve.ps1'
$oldPath=$env:PATH
try{
  $env:PATH=''
  Assert (-not (Get-Command git -ErrorAction SilentlyContinue)) 'handoff observer needs no Git executable'
  $first=(& $observer -ProjectRoot $project -RepositoryPath $repo -OutputFormat Json)|ConvertFrom-Json
  Assert ($first.status -ceq 'OBSERVED' -and $first.authority -ceq 'OBSERVED_NOT_AUTHENTICATED') 'handoff is observation not trusted authorization'
  $snapshot=Get-GitLiteDleSnapshot -RepositoryPath $repo -WorksetId $doc.handoffId
  Assert ($snapshot.Head -ceq $first.head -and $snapshot.Recovery -ceq 'RECONCILE_REQUIRED') 'handoff observed into Git-backed DLE event'
  Assert ($snapshot.Event.evidenceRefs[0] -ceq ('sha256:'+$first.handoffDigestSha256)) 'original handoff bytes linked by SHA256'
  Assert ($snapshot.NextBaton -match 'AGENTS.md' -and $snapshot.Event.message -notmatch 'SECRET_MARKER') 'minimal cold-start baton without source/private nextActions'
  Assert ([IO.File]::ReadAllText($pointer) -match 'SECRET_MARKER') 'observer never rewrites existing authoritative handoff pointer'
  $replay=(& $observer -ProjectRoot $project -RepositoryPath $repo -OutputFormat Json)|ConvertFrom-Json
  Assert ($replay.replay -and $replay.head -ceq $first.head) 'unchanged handoff digest replay is idempotent'
  $doc.promptPath='../escape'
  [IO.File]::WriteAllText($pointer,(ConvertTo-Json -InputObject $doc -Depth 6 -Compress),[Text.UTF8Encoding]::new($false))
  $denied=$false
  try{$null=& $observer -ProjectRoot $project -RepositoryPath $repo -ExpectedHead $first.head -OutputFormat Json}catch{$denied=$true}
  Assert $denied 'unsafe handoff path refused'
  Assert ((Get-GitLiteDleSnapshot -RepositoryPath $repo -WorksetId $doc.handoffId).Head -ceq $first.head) 'denied handoff does not change DLE reference'
  $doc.promptPath='agent-exchange/prompts/synthetic-v2.md'
  [IO.File]::WriteAllText($pointer,(ConvertTo-Json -InputObject $doc -Depth 6 -Compress),[Text.UTF8Encoding]::new($false))
  $second=(& $observer -ProjectRoot $project -RepositoryPath $repo -ExpectedHead $first.head -OutputFormat Json)|ConvertFrom-Json
  Assert ($second.head -cne $first.head -and $second.handoffDigestSha256 -cne $first.handoffDigestSha256) 'new handoff content creates new evidence-linked commit'
}finally{$env:PATH=$oldPath}
$null=@(& git -C $repo fsck --full --no-reflogs 2>&1)
Assert ($LASTEXITCODE -eq 0) 'Git fsck verifies synthetic handoff DLE history'
Write-Output 'PSGITLITE_DLE_HANDOFF_ADAPTER_PASS'
