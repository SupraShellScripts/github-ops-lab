# Public-original synthetic deterministic size/property qualification.
# Git CLI is strictly the independent oracle, never a product dependency.
Set-StrictMode -Version Latest
$ErrorActionPreference='Stop'
Import-Module (Join-Path $PSScriptRoot 'PSGitLiteCore.psm1') -Force
$checks=0
function Assert([bool]$ok,[string]$name) {
  $script:checks++
  if(-not $ok){throw ("FAIL "+$script:checks+" "+$name)}
  Write-Output ("PASS "+$script:checks+" "+$name)
}
function GitHash([string]$repo,[string]$path) {
  $result=@(& git -C $repo hash-object $path 2>&1)
  if($LASTEXITCODE -ne 0){throw 'Independent git hash-object failed'}
  return [string]$result[0]
}
$root=[IO.Path]::Combine([IO.Path]::GetTempPath(),('psgit-property-'+[guid]::NewGuid().ToString('N')))
[void][IO.Directory]::CreateDirectory($root)
try {
  $null=New-GitLiteRepository -Path $root
  $file=[IO.Path]::Combine($root,'bytes.bin')
  # Empty, compression block boundaries, medium and 1 MiB objects.
  $lengths=@(0,1,2,3,7,31,32,63,64,127,128,255,256,511,512,1023,1024,
             4095,4096,16383,16384,65535,65536,131071,131072,262144,1048576)
  $rng=[System.Random]::new(20261103)
  foreach($n in $lengths) {
    $bytes=New-Object byte[] $n
    if($n -gt 0){$rng.NextBytes($bytes)}
    [IO.File]::WriteAllBytes($file,$bytes)
    $expected=GitHash $root $file
    $actual=New-GitLiteObject -RepositoryPath $root -Type blob -Payload $bytes
    Assert ($actual -ceq $expected) ('OID equals independent Git for '+$n+' bytes')
    $stored=Get-GitLiteObject -RepositoryPath $root -Sha $actual
    Assert ($stored.Type -ceq 'blob' -and $stored.Data.Length -eq $n) ('Git object type/length '+$n)
    Assert ([Convert]::ToBase64String($stored.Data) -ceq [Convert]::ToBase64String($bytes)) ('Exact blob byte roundtrip '+$n)
  }
  Write-Output ('PUBLIC_PROPERTY_PASS count='+$script:checks+' objects='+$lengths.Count+' powershell='+$PSVersionTable.PSVersion.ToString())
}
finally { if([IO.Directory]::Exists($root)){[IO.Directory]::Delete($root,$true)} }
