#requires -Version 5.1
# Public-safe object-store redirection negative tests. Disposable RUNNER_TEMP only.
Set-StrictMode -Version Latest
$ErrorActionPreference='Stop'
Import-Module (Join-Path (Split-Path $PSScriptRoot -Parent) 'psgitlite-native/PSGitLiteCore.psm1') -Force
function Assert([bool]$Ok,[string]$Label){if(!$Ok){throw ('FAIL '+$Label)};Write-Output ('PASS '+$Label)}
$root=Join-Path $env:RUNNER_TEMP 'psgitlite-object-redirect-fixture'
if([IO.Directory]::Exists($root)){throw 'FIXTURE_ALREADY_EXISTS'}
$null=New-GitLiteRepository -Path $root
$payload=[Text.Encoding]::UTF8.GetBytes('hello world'+[char]10)
$blob=New-GitLiteObject -RepositoryPath $root -Type blob -Payload $payload
Assert ($blob -ceq '3b18e512dba79e4c8300dd08aeb37f8e728b8dad') 'independent known Git object SHA'
$normal=Get-GitLiteObject -RepositoryPath $root -Sha $blob
Assert ($normal.Type -ceq 'blob') 'baseline loose object readable'
if($PSVersionTable.PSVersion.Major -gt 5 -and -not $IsWindows){
  $objects=Join-Path $root '.git/objects'
  $prefix=Join-Path $objects '3b'
  $outside=Join-Path $env:RUNNER_TEMP 'psgitlite-object-outside'
  [void][IO.Directory]::CreateDirectory($outside)
  $save=Join-Path $env:RUNNER_TEMP 'psgitlite-object-prefix-original'
  [IO.Directory]::Move($prefix,$save)
  $null=New-Item -ItemType SymbolicLink -Path $prefix -Target $outside
  try{
    $refused=$false
    try{$null=Get-GitLiteObject -RepositoryPath $root -Sha $blob}
    catch{$refused=($_.Exception.Message -match 'DLE_OBJECT_REPARSE_REFUSED')}
    Assert $refused 'symlinked prefix read refused explicitly'
    $refused=$false
    try{$null=New-GitLiteObject -RepositoryPath $root -Type blob -Payload $payload}
    catch{$refused=($_.Exception.Message -match 'DLE_OBJECT_REPARSE_REFUSED')}
    Assert $refused 'symlinked prefix write refused explicitly'
    Assert (@([IO.Directory]::EnumerateFileSystemEntries($outside)).Count -eq 0) 'no object escaped repository'
  }finally{
    Remove-Item -LiteralPath $prefix -Force
    [IO.Directory]::Move($save,$prefix)
  }
  $path=Join-Path $prefix $blob.Substring(2)
  $savedFile=Join-Path $env:RUNNER_TEMP 'psgitlite-object-file-original'
  [IO.File]::Move($path,$savedFile)
  $null=New-Item -ItemType SymbolicLink -Path $path -Target $savedFile
  try{
    $refused=$false
    try{$null=Get-GitLiteObject -RepositoryPath $root -Sha $blob}
    catch{$refused=($_.Exception.Message -match 'DLE_OBJECT_REPARSE_REFUSED')}
    Assert $refused 'symlinked object file read refused explicitly'
  }finally{
    Remove-Item -LiteralPath $path -Force
    [IO.File]::Move($savedFile,$path)
  }
}else{
  Write-Output 'SKIP symlink-specific fixture: requires public Linux runner'
}
Assert ((Get-GitLiteObject -RepositoryPath $root -Sha $blob).Sha -ceq $blob) 'restored object readable'
$null=@(& git -C $root fsck --full --no-reflogs 2>&1)
Assert ($LASTEXITCODE -eq 0) 'native Git fsck after redirection negatives'
Write-Output 'PSGITLITE_OBJECT_REDIRECT_NATIVE_PASS'
