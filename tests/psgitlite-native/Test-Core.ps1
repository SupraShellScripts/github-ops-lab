# Public-safe synthetic native core qualification; independent Git CLI is test oracle only.
Set-StrictMode -Version Latest
$ErrorActionPreference='Stop'
Import-Module (Join-Path $PSScriptRoot 'PSGitLiteCore.psm1') -Force
function Assert([bool]$pass,[string]$name) {
  if(-not $pass){throw "FAIL $name"}
  Write-Output "PASS $name"
}
function GitOracle([string]$Repo,[string[]]$GitArguments) {
  $out=@(& git -C $Repo @GitArguments 2>&1)
  if($LASTEXITCODE -ne 0){throw "Git independent oracle failed: $($GitArguments -join ' '): $($out -join ' ')"}
  return ,([string[]]$out)
}
$dir=[IO.Path]::Combine([IO.Path]::GetTempPath(),('psgitlite-cloud-'+[guid]::NewGuid().ToString('N')))
[void][IO.Directory]::CreateDirectory($dir)
try {
  $r=New-GitLiteRepository -Path $dir
  Assert ([IO.Directory]::Exists([IO.Path]::Combine($dir,'.git'))) 'init creates Git metadata'
  $native=GitOracle $dir @('rev-parse','--is-inside-work-tree')
  Assert ($native[0] -eq 'true') 'Git reads PowerShell-generated repository'
  $file=[IO.Path]::Combine($dir,'hello.txt')
  [IO.File]::WriteAllBytes($file,[Text.Encoding]::UTF8.GetBytes("hello"+[char]10))
  $first=New-GitLiteSingleFileCommit -RepositoryPath $dir -FileName 'hello.txt' -Message 'initial' -AuthorName 'Synthetic Tester' -AuthorEmail 'test@example.invalid'
  Assert ($first.Blob -ceq 'ce013625030ba8dba906f756967f9e9ca394464a') 'canonical blob Git SHA'
  $head=GitOracle $dir @('rev-parse','HEAD')
  Assert ($head[0] -ceq $first.Commit) 'Git resolves PowerShell commit'
  $sha=GitOracle $dir @('rev-parse','HEAD^{tree}')
  Assert ($sha[0] -ceq $first.Tree) 'Git verifies PowerShell tree SHA'
  $obj=Get-GitLiteObject -RepositoryPath $dir -Sha $first.Blob
  Assert ($obj.Type -eq 'blob' -and [Text.Encoding]::UTF8.GetString($obj.Data) -ceq ("hello"+[char]10)) 'native reader round-trip'
  $null=GitOracle $dir @('fsck','--full','--no-reflogs')
  Assert $true 'independent git fsck initial commit'
  [IO.File]::WriteAllBytes($file,[byte[]]@(0,1,2,255,0,10))
  $second=New-GitLiteSingleFileCommit -RepositoryPath $dir -FileName 'hello.txt' -Message 'binary' -AuthorName 'Synthetic Tester' -AuthorEmail 'test@example.invalid'
  Assert ($second.Parent -ceq $first.Commit) 'parent ancestry'
  Assert ((GitOracle $dir @('rev-parse','HEAD'))[0] -ceq $second.Commit) 'second commit readable by Git'
  $null=GitOracle $dir @('fsck','--full','--no-reflogs')
  Assert $true 'independent git fsck second commit'
  $rejected=$false
  try {$null=New-GitLiteSingleFileCommit -RepositoryPath $dir -FileName '../escape.txt' -Message 'bad' -AuthorName 'Tester' -AuthorEmail 'test@example.invalid'} catch {$rejected=$true}
  Assert $rejected 'reject path traversal'
  $objPath=[IO.Path]::Combine($dir,'.git','objects',$first.Blob.Substring(0,2),$first.Blob.Substring(2))
  $bytes=[IO.File]::ReadAllBytes($objPath)
  $bytes[$bytes.Length-1]=[byte]($bytes[$bytes.Length-1] -bxor 1)
  [IO.File]::WriteAllBytes($objPath,$bytes)
  $rejected=$false
  try{$null=Get-GitLiteObject -RepositoryPath $dir -Sha $first.Blob}catch{$rejected=$true}
  Assert $rejected 'corrupted loose object refused'
  Write-Output ('PSGITLITE_PUBLIC_NATIVE_PASS powershell='+$PSVersionTable.PSVersion+' os='+[Environment]::OSVersion.VersionString)
} finally {
  if([IO.Directory]::Exists($dir)){[IO.Directory]::Delete($dir,$true)}
}