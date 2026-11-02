# PSGitLite: public-safe reference core. Windows PowerShell 5.1 + built-in .NET.
# Runtime: no git.exe, Add-Type, child process, native library, COM or network.
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$script:utf8 = [Text.UTF8Encoding]::new($false,$true)
$script:ascii = [Text.Encoding]::ASCII

function ConvertTo-LiteHex([byte[]]$B) {
  return ([BitConverter]::ToString($B)).Replace('-','').ToLowerInvariant()
}
function Get-LiteSha([byte[]]$B) {
  $h=[Security.Cryptography.SHA1]::Create()
  try { return ConvertTo-LiteHex $h.ComputeHash($B) } finally { $h.Dispose() }
}
function Get-LiteAdler([byte[]]$Bytes) {
  [uint32]$a=1; [uint32]$b=0
  foreach($v in $Bytes){$a=[uint32](($a+[uint32]$v)%65521);$b=[uint32](($b+$a)%65521)}
  return [uint32](([uint64]$b -shl 16) -bor [uint64]$a)
}
function Write-Lite32([IO.Stream]$Stream,[uint32]$Number) {
  foreach($shift in @(24,16,8,0)){$Stream.WriteByte([byte](($Number -shr $shift) -band 255))}
}
function Read-Lite32([byte[]]$Bytes,[int]$Offset) {
  if($Offset -lt 0 -or $Offset+4 -gt $Bytes.Length){throw 'Truncated integer'}
  [uint64]$n=0
  for($i=0;$i -lt 4;$i++){$n=($n -shl 8) -bor [uint64]$Bytes[$Offset+$i]}
  return [uint32]$n
}
function Assert-LiteRepo([string]$Path) {
  $root=[IO.Path]::GetFullPath($Path);$git=[IO.Path]::Combine($root,'.git')
  if(-not [IO.Directory]::Exists($git)){throw 'Repository not initialized'}
  $h=[IO.File]::ReadAllText([IO.Path]::Combine($git,'HEAD')).Trim()
  if($h -cne 'ref: refs/heads/main'){throw 'Only main branch is supported'}
  return [pscustomobject]@{ Root=$root; Git=$git; Ref=[IO.Path]::Combine($git,'refs','heads','main') }
}
function New-GitLiteRepository {
  [CmdletBinding(SupportsShouldProcess=$true)]param([Parameter(Mandatory)][string]$Path)
  $root=[IO.Path]::GetFullPath($Path);$git=[IO.Path]::Combine($root,'.git')
  if([IO.Directory]::Exists($git) -or [IO.File]::Exists($git)){throw 'Existing Git directory'}
  if($PSCmdlet.ShouldProcess($root,'Create disposable Git SHA-1 repository')){
    [void][IO.Directory]::CreateDirectory([IO.Path]::Combine($git,'objects'))
    [void][IO.Directory]::CreateDirectory([IO.Path]::Combine($git,'refs','heads'))
    [IO.File]::WriteAllText([IO.Path]::Combine($git,'HEAD'),"ref: refs/heads/main`n",$script:utf8)
    [IO.File]::WriteAllText([IO.Path]::Combine($git,'config'),"[core]`n`trepositoryformatversion = 0`n`tbare = false`n",$script:utf8)
    return $root
  }
}
function New-GitLiteObject {
  [CmdletBinding()]param([Parameter(Mandatory)][string]$RepositoryPath,
    [Parameter(Mandatory)][ValidateSet('blob','tree','commit')][string]$Type,
    [Parameter(Mandatory)][byte[]]$Payload)
  if($Payload.Length -gt 33554432){throw 'Payload bound'}
  $repo=Assert-LiteRepo $RepositoryPath
  $prefix=$script:ascii.GetBytes("$Type $($Payload.Length)")
  $ms=[IO.MemoryStream]::new()
  try{
    $ms.Write($prefix,0,$prefix.Length);$ms.WriteByte(0);$ms.Write($Payload,0,$Payload.Length)
    $raw=$ms.ToArray();$id=Get-LiteSha $raw
    $dir=[IO.Path]::Combine($repo.Git,'objects',$id.Substring(0,2))
    $dest=[IO.Path]::Combine($dir,$id.Substring(2))
    if([IO.File]::Exists($dest)){return $id}
    [void][IO.Directory]::CreateDirectory($dir)
    $compressed=[IO.MemoryStream]::new()
    try{
      $compressed.WriteByte(0x78);$compressed.WriteByte(0x9c)
      $def=[IO.Compression.DeflateStream]::new($compressed,[IO.Compression.CompressionMode]::Compress,$true)
      try{$def.Write($raw,0,$raw.Length)}finally{$def.Dispose()}
      Write-Lite32 $compressed (Get-LiteAdler $raw)
      $tmp=[IO.Path]::Combine($dir,([guid]::NewGuid().ToString('N')+'.tmp'))
      [IO.File]::WriteAllBytes($tmp,$compressed.ToArray())
      try{[IO.File]::Move($tmp,$dest)}finally{if([IO.File]::Exists($tmp)){[IO.File]::Delete($tmp)}}
    }finally{$compressed.Dispose()}
    return $id
  }finally{$ms.Dispose()}
}
function Get-GitLiteObject {
  [CmdletBinding()]param([Parameter(Mandatory)][string]$RepositoryPath,
    [Parameter(Mandatory)][string]$Sha)
  if($Sha -cnotmatch '^[a-f0-9]{40}$'){throw 'Invalid object id'}
  $repo=Assert-LiteRepo $RepositoryPath
  $file=[IO.Path]::Combine($repo.Git,'objects',$Sha.Substring(0,2),$Sha.Substring(2))
  $z=[IO.File]::ReadAllBytes($file)
  if($z.Length -lt 7 -or $z[0] -ne 0x78 -or (($z[0]*256+$z[1])%31) -ne 0){throw 'Invalid zlib'}
  $input=[IO.MemoryStream]::new($z,$false)
  $output=[IO.MemoryStream]::new()
  try{
    $input.Position=2
    $def=[IO.Compression.DeflateStream]::new($input,[IO.Compression.CompressionMode]::Decompress,$true)
    try{
      $buf=New-Object byte[] 8192
      while(($n=$def.Read($buf,0,$buf.Length)) -gt 0){
        if($output.Length+$n -gt 33554496){throw 'Expanded object bound'}
        $output.Write($buf,0,$n)
      }
    }finally{$def.Dispose()}
    $raw=$output.ToArray()
  }finally{$input.Dispose();$output.Dispose()}
  if((Read-Lite32 $z ($z.Length-4)) -ne (Get-LiteAdler $raw)){throw 'Adler mismatch'}
  if((Get-LiteSha $raw) -cne $Sha){throw 'Object hash mismatch'}
  $nul=[Array]::IndexOf($raw,[byte]0)
  if($nul -lt 4 -or $nul -gt 40){throw 'Invalid Git header'}
  $header=$script:ascii.GetString($raw,0,$nul)
  if($header -cmatch '^(blob|tree|commit) ([0-9]+)$'){$type=$Matches[1];$size=[int]$Matches[2]}else{throw 'Invalid object header'}
  if($size -ne ($raw.Length-$nul-1)){throw 'Invalid object size'}
  $data=New-Object byte[] $size
  [Array]::Copy($raw,$nul+1,$data,0,$size)
  return [pscustomobject]@{Type=$type;Sha=$Sha;Data=$data}
}
function New-GitLiteSingleFileCommit {
  [CmdletBinding(SupportsShouldProcess=$true)]param(
    [Parameter(Mandatory)][string]$RepositoryPath,
    [Parameter(Mandatory)][string]$FileName,
    [Parameter(Mandatory)][string]$Message,
    [Parameter(Mandatory)][string]$AuthorName,
    [Parameter(Mandatory)][string]$AuthorEmail)
  if($FileName -cnotmatch '^[a-zA-Z0-9_.-]+$' -or $FileName -eq '.git'){throw 'Restricted single-file name'}
  if($AuthorName -match '[<>\x00\r\n]' -or $AuthorEmail -cnotmatch '^[^<>\s@]+@[^<>\s@]+$' -or $Message.Contains([char]0)){throw 'Invalid commit fields'}
  $repo=Assert-LiteRepo $RepositoryPath
  $source=[IO.Path]::Combine($repo.Root,$FileName)
  $file=Get-Item -LiteralPath $source -Force
  if($file.PSIsContainer -or ($file.Attributes -band [IO.FileAttributes]::ReparsePoint)){throw 'Unsupported file type'}
  if($PSCmdlet.ShouldProcess($repo.Ref,'Create single-file Git commit')){
    $blob=New-GitLiteObject $repo.Root 'blob' ([IO.File]::ReadAllBytes($source))
    $treeMs=[IO.MemoryStream]::new()
    try{
      $bytes=$script:utf8.GetBytes("100644 $FileName")
      $treeMs.Write($bytes,0,$bytes.Length);$treeMs.WriteByte(0)
      for($i=0;$i -lt 40;$i+=2){$treeMs.WriteByte([Convert]::ToByte($blob.Substring($i,2),16))}
      $tree=New-GitLiteObject $repo.Root 'tree' $treeMs.ToArray()
    }finally{$treeMs.Dispose()}
    $parent=if([IO.File]::Exists($repo.Ref)){[IO.File]::ReadAllText($repo.Ref).Trim()}else{$null}
    if($parent -and $parent -cnotmatch '^[a-f0-9]{40}$'){throw 'Invalid parent'}
    $now=[DateTimeOffset]::Now
    $mins=[int]$now.Offset.TotalMinutes
    $sign=if($mins -lt 0){'-'}else{'+'}
    $tz='{0}{1:D2}{2:D2}' -f $sign,[int][Math]::Floor([Math]::Abs($mins)/60),([Math]::Abs($mins)%60)
    $ident="$AuthorName <$AuthorEmail> $($now.ToUnixTimeSeconds()) $tz"
    $parentLine=if($parent){"parent $parent`n"}else{''}
    $body="tree $tree`n$parentLine"+"author $ident`ncommitter $ident`n`n$Message`n"
    $commit=New-GitLiteObject $repo.Root 'commit' ($script:utf8.GetBytes($body))
    $check=if([IO.File]::Exists($repo.Ref)){[IO.File]::ReadAllText($repo.Ref).Trim()}else{$null}
    if($check -cne $parent){throw 'Concurrent branch update'}
    $lock=$repo.Ref+'.lock'
    $out=[IO.FileStream]::new($lock,[IO.FileMode]::CreateNew,[IO.FileAccess]::Write,[IO.FileShare]::None)
    try{$b=$script:ascii.GetBytes("$commit`n");$out.Write($b,0,$b.Length)}finally{$out.Dispose()}
    try{
      if([IO.File]::Exists($repo.Ref)){
        $backup=$repo.Ref+'.psg-backup-'+[guid]::NewGuid().ToString('N')
        [IO.File]::Replace($lock,$repo.Ref,$backup)
        if([IO.File]::Exists($backup)){[IO.File]::Delete($backup)}
      }
      else{[IO.File]::Move($lock,$repo.Ref)}
    }finally{if([IO.File]::Exists($lock)){[IO.File]::Delete($lock)}}
    return [pscustomobject]@{Blob=$blob;Tree=$tree;Commit=$commit;Parent=$parent}
  }
}
Export-ModuleMember -Function New-GitLiteRepository,New-GitLiteObject,Get-GitLiteObject,New-GitLiteSingleFileCommit
