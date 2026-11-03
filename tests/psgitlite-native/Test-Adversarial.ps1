# Public-original synthetic adversarial qualification. No private data.
# Git executable is ONLY used in the independent test oracle.
Set-StrictMode -Version Latest
$ErrorActionPreference='Stop'
Import-Module (Join-Path $PSScriptRoot 'PSGitLiteCore.psm1') -Force
$script:checks=0
function Assert([bool]$ok,[string]$name) {
  $script:checks++
  if(-not $ok){throw ("FAIL {0}/{1}" -f $script:checks,$name)}
  Write-Output ("PASS {0}/{1}" -f $script:checks,$name)
}
function Refuses([scriptblock]$block,[string]$name) {
  $rejected=$false
  try{$null=& $block}catch{$rejected=$true}
  Assert $rejected $name
}
function Oracle([string]$root,[string[]]$GitArguments) {
  $lines=@(& git -C $root @GitArguments 2>&1)
  if($LASTEXITCODE -ne 0){throw ('Git oracle failure: '+($GitArguments -join ' '))}
  return ,([string[]]$lines)
}
function EqualBytes([byte[]]$a,[byte[]]$b) {
  return [Convert]::ToBase64String($a) -ceq [Convert]::ToBase64String($b)
}
$root=[IO.Path]::Combine([IO.Path]::GetTempPath(),('psgit-adversarial-'+[guid]::NewGuid().ToString('N')))
[void][IO.Directory]::CreateDirectory($root)
try {
  $null=New-GitLiteRepository -Path $root
  Assert ([IO.Directory]::Exists([IO.Path]::Combine($root,'.git'))) 'repo initialized'
  $empty=[byte[]]@()
  $emptyId=New-GitLiteObject -RepositoryPath $root -Type blob -Payload $empty
  Assert ($emptyId -ceq 'e69de29bb2d1d6434b8b29ae775ad8c2e48c5391') 'empty blob Git OID'
  Assert ((Oracle $root @('cat-file','-t',$emptyId))[0] -ceq 'blob') 'Git independently reads empty blob'
  Assert ((Get-GitLiteObject -RepositoryPath $root -Sha $emptyId).Data.Length -eq 0) 'empty payload roundtrip'
  Assert ((New-GitLiteObject -RepositoryPath $root -Type blob -Payload $empty) -ceq $emptyId) 'valid object reuse'

  $utf8=[Text.UTF8Encoding]::new($false,$true)
  $message="Gr"+[char]0x00FC+[char]0x00DF+" Gott "+[char]0x0E2A+[char]0x0E27+[char]0x0E31+[char]0x0E2A+[char]0x0E14+[char]0x0E35
  $file=[IO.Path]::Combine($root,'sample.txt')
  [IO.File]::WriteAllBytes($file,$utf8.GetBytes($message+[char]10))
  $textBlob=New-GitLiteObject -RepositoryPath $root -Type blob -Payload ([IO.File]::ReadAllBytes($file))
  Assert ($textBlob -ceq (Oracle $root @('hash-object',$file))[0]) 'Unicode blob equals independent Git OID'
  Assert (EqualBytes (Get-GitLiteObject -RepositoryPath $root -Sha $textBlob).Data ([IO.File]::ReadAllBytes($file))) 'Unicode bytes roundtrip'
  $binary=[byte[]]@(0,1,2,255,13,10,0)
  [IO.File]::WriteAllBytes($file,$binary)
  $binaryId=New-GitLiteObject -RepositoryPath $root -Type blob -Payload $binary
  Assert ($binaryId -ceq (Oracle $root @('hash-object',$file))[0]) 'binary blob independent OID'
  Assert (EqualBytes (Get-GitLiteObject -RepositoryPath $root -Sha $binaryId).Data $binary) 'binary roundtrip'
  Refuses {Get-GitLiteObject -RepositoryPath $root -Sha ('f'*40)} 'unknown object rejected'
  Refuses {Get-GitLiteObject -RepositoryPath $root -Sha '../bad'} 'bad object identifier rejected'

  $stored=[IO.Path]::Combine($root,'.git','objects',$binaryId.Substring(0,2),$binaryId.Substring(2))
  $valid=[IO.File]::ReadAllBytes($stored)
  $corrupt=[byte[]]$valid.Clone()
  $corrupt[$corrupt.Length-1]=[byte]($corrupt[$corrupt.Length-1] -bxor 1)
  [IO.File]::WriteAllBytes($stored,$corrupt)
  Refuses {Get-GitLiteObject -RepositoryPath $root -Sha $binaryId} 'existing corrupted object refused on read'
  Refuses {New-GitLiteObject -RepositoryPath $root -Type blob -Payload $binary} 'existing corrupted object refused on write'
  [IO.File]::WriteAllBytes($stored,$valid)
  Assert ((New-GitLiteObject -RepositoryPath $root -Type blob -Payload $binary) -ceq $binaryId) 'repaired object reused'

  [IO.File]::WriteAllBytes($file,$utf8.GetBytes("version 1"+[char]10))
  $first=New-GitLiteSingleFileCommit -RepositoryPath $root -FileName 'sample.txt' -Message 'first' -AuthorName 'Synthetic Tester' -AuthorEmail 'tester@example.invalid'
  Assert ($first.Commit -ceq (Oracle $root @('rev-parse','HEAD'))[0]) 'first commit Git-readable'
  $null=Oracle $root @('fsck','--full','--no-reflogs')
  Assert $true 'first commit fsck'
  [IO.File]::WriteAllBytes($file,$utf8.GetBytes("version 2"+[char]10))
  $headBefore=(Oracle $root @('rev-parse','HEAD'))[0]
  $lock=[IO.Path]::Combine($root,'.git','refs','heads','main.lock')
  [IO.File]::WriteAllBytes($lock,[byte[]]@(1,2,3))
  Refuses {New-GitLiteSingleFileCommit -RepositoryPath $root -FileName 'sample.txt' -Message 'locked' -AuthorName 'Synthetic Tester' -AuthorEmail 'tester@example.invalid'} 'existing lock denied'
  Assert ((Oracle $root @('rev-parse','HEAD'))[0] -ceq $headBefore) 'HEAD unchanged after lock denial'
  Assert ([IO.File]::Exists($lock)) 'foreign lock preserved'
  [IO.File]::Delete($lock)
  $second=New-GitLiteSingleFileCommit -RepositoryPath $root -FileName 'sample.txt' -Message 'second' -AuthorName 'Synthetic Tester' -AuthorEmail 'tester@example.invalid'
  Assert ($second.Parent -ceq $headBefore) 'second commit parent'
  Assert ($second.Commit -ceq (Oracle $root @('rev-parse','HEAD'))[0]) 'second commit Git-readable'
  $null=Oracle $root @('fsck','--full','--no-reflogs')
  Assert $true 'second commit fsck'

  Refuses {New-GitLiteSingleFileCommit -RepositoryPath $root -FileName '../escape' -Message x -AuthorName Tester -AuthorEmail 'tester@example.invalid'} 'traversal rejected'
  Refuses {New-GitLiteSingleFileCommit -RepositoryPath $root -FileName '.git' -Message x -AuthorName Tester -AuthorEmail 'tester@example.invalid'} 'Git metadata rejected'
  Refuses {New-GitLiteSingleFileCommit -RepositoryPath $root -FileName 'sample.txt' -Message x -AuthorName ("Bad"+[char]10+"Name") -AuthorEmail 'tester@example.invalid'} 'multiline author rejected'
  Refuses {New-GitLiteSingleFileCommit -RepositoryPath $root -FileName 'sample.txt' -Message x -AuthorName Tester -AuthorEmail 'not-an-email'} 'invalid email rejected'
  Write-Output ('PUBLIC_ADVERSARIAL_PASS assertions='+$script:checks+' powershell='+$PSVersionTable.PSVersion.ToString())
}
finally {
  if([IO.Directory]::Exists($root)){[IO.Directory]::Delete($root,$true)}
}
