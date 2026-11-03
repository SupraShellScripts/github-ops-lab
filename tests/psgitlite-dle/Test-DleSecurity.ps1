# Public-original negative + multilingual DLE fixtures.
Set-StrictMode -Version Latest
$ErrorActionPreference='Stop'
Import-Module (Join-Path $PSScriptRoot 'PSGitLiteDle.psm1') -Force
function Assert([bool]$Ok,[string]$Label) {
  if(!$Ok){throw ('FAIL '+$Label)}
  Write-Output ('PASS '+$Label)
}
$root=[IO.Path]::Combine($env:RUNNER_TEMP,'psgitlite-dle-security')
$null=Initialize-GitLiteDle -RepositoryPath $root
foreach($bad in @('..','a/../b','CON','x.lock','a..b','unsafe:name','a\b')){
  $denied=$false
  try{$null=Get-GitLiteDleSnapshot -RepositoryPath $root -WorksetId $bad}catch{$denied=$true}
  Assert $denied ('dangerous workset identifier refused '+$bad)
}
$badHash=$false
try{
  $null=New-GitLiteDleCheckpoint -RepositoryPath $root -WorksetId unicode -RequestId security01 -StepId observe -Phase Observe -Status INTENT -Message 'bad digest' -NextBaton 'refuse' -SourceRootDigest 'not-a-digest'
}catch{$badHash=$true}
Assert $badHash 'malformed source identity digest refused'
$badApproval=$false
try{
  $null=New-GitLiteDleCheckpoint -RepositoryPath $root -WorksetId unicode -RequestId security02 -StepId observe -Phase Observe -Status INTENT -Message 'oversized grant reference' -NextBaton 'refuse' -ApprovalRef ('a'*257)
}catch{$badApproval=$true}
Assert $badApproval 'overbound approval reference refused'
$message='Gr'+[char]0x00FC+[char]0x00DF+'e '+[char]0x0E2A+[char]0x0E27+[char]0x0E31+[char]0x0E2A+[char]0x0E14+[char]0x0E35
$baton='Pr'+[char]0x00FC+'fen / '+[char]0x0E15+[char]0x0E48+[char]0x0E2D+[char]0x0E44+[char]0x0E1B
$one=New-GitLiteDleCheckpoint -RepositoryPath $root -WorksetId unicode -RequestId unicode001 -StepId observe -Phase Observe -Status VERIFIED -Message $message -NextBaton $baton -EvidenceRefs @('fixture:de','fixture:th')
$read=Get-GitLiteDleSnapshot -RepositoryPath $root -WorksetId unicode
Assert ($read.Event.message -ceq $message -and $read.NextBaton -ceq $baton) 'UTF-8 German/Thai event and baton round-trip'
$ref=[IO.Path]::Combine($root,'.git','refs','airea51','dle','unicode')
$original=[IO.File]::ReadAllBytes($ref)
try{
  [IO.File]::WriteAllText($ref,'malformed')
  $denied=$false
  try{$null=Get-GitLiteDleSnapshot -RepositoryPath $root -WorksetId unicode}catch{$denied=$true}
  Assert $denied 'malformed DLE ref refused'
}finally{[IO.File]::WriteAllBytes($ref,$original)}
if($PSVersionTable.PSVersion.Major -gt 5){
  $link=[IO.Path]::Combine($root,'.git','refs','airea51','dle','symlinktest')
  $null=New-Item -ItemType SymbolicLink -Path $link -Target $ref
  try{
    $denied=$false
    try{$null=Get-GitLiteDleSnapshot -RepositoryPath $root -WorksetId symlinktest}catch{$denied=$true}
    Assert $denied 'redirecting symbolic DLE ref refused'
  }finally{Remove-Item -LiteralPath $link -Force}
}
$head=(Get-GitLiteDleSnapshot -RepositoryPath $root -WorksetId unicode).Head
Assert ($head -ceq $one.Head) 'tamper-negative tests preserve DLE source head'
$null=@(& git -C $root fsck --full --no-reflogs 2>&1)
Assert ($LASTEXITCODE -eq 0) 'multilingual and negative Git tree accepted by native Git'
Write-Output 'PSGITLITE_DLE_SECURITY_PASS'
