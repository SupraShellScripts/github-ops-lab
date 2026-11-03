# PSGitLite experimental read-only packed-object implementation.
# PowerShell 5.1 + built-in .NET only. SHA-1 pack v2, index v2, OFS/REF delta.
# Source-only public-safe fixture. No process, git executable, COM, Add-Type or network.
Set-StrictMode -Version Latest
$ErrorActionPreference='Stop'
$script:PackBound=67108864
$script:ExpandBound=33554432
$script:Ascii=[Text.Encoding]::ASCII

function Read-PackU32([byte[]]$B,[long]$P){
    if($P -lt 0 -or $P + 4 -gt $B.Length){throw 'Truncated pack integer'}
    [uint64]$n=0
    for($i=0;$i -lt 4;$i++){$n=($n -shl 8) -bor [uint64]$B[$P+$i]}
    return [uint32]$n
}
function Read-PackU64([byte[]]$B,[long]$P){
    if($P -lt 0 -or $P + 8 -gt $B.Length){throw 'Truncated 64-bit pack integer'}
    [uint64]$n=0
    for($i=0;$i -lt 8;$i++){$n=($n -shl 8) -bor [uint64]$B[$P+$i]}
    return $n
}
function Get-PackHex([byte[]]$B){return ([BitConverter]::ToString($B)).Replace('-','').ToLowerInvariant()}
function Get-PackSha([byte[]]$B){
    $h=[Security.Cryptography.SHA1]::Create()
    try{return Get-PackHex $h.ComputeHash($B)}finally{$h.Dispose()}
}
function Get-PackSlice([byte[]]$B,[long]$Start,[long]$Length){
    if($Start -lt 0 -or $Length -lt 0 -or $Start+$Length -gt $B.Length){throw 'Pack slice out of bounds'}
    $out=New-Object byte[] ([int]$Length)
    [Array]::Copy($B,[int]$Start,$out,0,[int]$Length)
    return ,$out
}
function Get-PackAdler([byte[]]$B){
    [uint32]$a=1;[uint32]$b=0
    foreach($v in $B){$a=[uint32](($a+[uint32]$v)%65521);$b=[uint32](($b+$a)%65521)}
    return [uint32](([uint64]$b -shl 16) -bor [uint64]$a)
}
function Get-PackObjectId([string]$Type,[byte[]]$Data){
    $h=$script:Ascii.GetBytes($Type+' '+$Data.Length)
    $m=[IO.MemoryStream]::new()
    try{
        $m.Write($h,0,$h.Length);$m.WriteByte(0);$m.Write($Data,0,$Data.Length)
        return Get-PackSha $m.ToArray()
    }finally{$m.Dispose()}
}
function Read-PackVarInt([byte[]]$B,[ref]$Position){
    [long]$value=0;[int]$shift=0
    do{
        if($Position.Value -ge $B.Length -or $shift -gt 49){throw 'Malformed delta variable integer'}
        $c=[int]$B[$Position.Value];$Position.Value++
        $value=$value -bor ([long]($c -band 127) -shl $shift)
        $shift+=7
    }while(($c -band 128) -ne 0)
    return $value
}
function Apply-PackDelta([byte[]]$Base,[byte[]]$Delta){
    [long]$at=0
    $baseSize=Read-PackVarInt $Delta ([ref]$at)
    $targetSize=Read-PackVarInt $Delta ([ref]$at)
    if($baseSize -ne $Base.Length -or $targetSize -gt $script:ExpandBound){throw 'Delta base/target size mismatch'}
    $out=[IO.MemoryStream]::new()
    try{
        while($at -lt $Delta.Length){
            $command=[int]$Delta[$at];$at++
            if(($command -band 128) -ne 0){
                [long]$offset=0;[long]$length=0
                for($k=0;$k -lt 4;$k++){
                    if(($command -band (1 -shl $k)) -ne 0){
                        if($at -ge $Delta.Length){throw 'Truncated delta copy offset'}
                        $offset=$offset -bor ([long]$Delta[$at] -shl ($k*8));$at++
                    }
                }
                for($k=0;$k -lt 3;$k++){
                    if(($command -band (16 -shl $k)) -ne 0){
                        if($at -ge $Delta.Length){throw 'Truncated delta copy length'}
                        $length=$length -bor ([long]$Delta[$at] -shl ($k*8));$at++
                    }
                }
                if($length -eq 0){$length=65536}
                if($offset+$length -gt $Base.Length -or $out.Length+$length -gt $targetSize){throw 'Delta copy beyond bounds'}
                $out.Write($Base,[int]$offset,[int]$length)
            }elseif($command -gt 0){
                if($at+$command -gt $Delta.Length -or $out.Length+$command -gt $targetSize){throw 'Delta insertion beyond bounds'}
                $out.Write($Delta,[int]$at,$command);$at+=$command
            }else{throw 'Invalid zero delta opcode'}
        }
        if($out.Length -ne $targetSize){throw 'Delta reconstructed length mismatch'}
        return ,$out.ToArray()
    }finally{$out.Dispose()}
}
function Open-PackContext([string]$IndexPath){
    $idx=[IO.File]::ReadAllBytes($IndexPath)
    if($idx.Length -gt $script:PackBound -or $idx.Length -lt 1072 -or
        $idx[0] -ne 255 -or $idx[1] -ne 116 -or $idx[2] -ne 79 -or $idx[3] -ne 99 -or
        (Read-PackU32 $idx 4) -ne 2){throw 'Unsupported Git pack index version'}
    $checksum=Get-PackHex (Get-PackSlice $idx ($idx.Length-20) 20)
    if((Get-PackSha (Get-PackSlice $idx 0 ($idx.Length-20))) -cne $checksum){throw 'Pack index SHA mismatch'}
    [uint32]$previous=0
    for($i=0;$i -lt 256;$i++){
        $n=Read-PackU32 $idx (8+$i*4)
        if($n -lt $previous){throw 'Invalid pack fanout table'}
        $previous=$n
    }
    [long]$count=$previous
    if($count -gt 100000){throw 'Pack object count exceeds bound'}
    [long]$names=1032
    [long]$crcs=$names+20*$count
    [long]$offsets=$crcs+4*$count
    [long]$large=$offsets+4*$count
    if($large+40 -gt $idx.Length){throw 'Truncated pack index entries'}
    $map=[System.Collections.Generic.Dictionary[string,long]]::new([StringComparer]::Ordinal)
    $orders=[System.Collections.Generic.List[long]]::new()
    for([long]$i=0;$i -lt $count;$i++){
        $oid=Get-PackHex (Get-PackSlice $idx ($names+$i*20) 20)
        if($map.ContainsKey($oid)){throw 'Duplicate object ID in pack index'}
        [uint64]$off=Read-PackU32 $idx ($offsets+$i*4)
        if(($off -band [uint64]2147483648) -ne 0){
            [long]$ix=[long]($off -band [uint64]2147483647)
            if($large+$ix*8+8 -gt $idx.Length-40){throw 'Invalid large-offset table reference'}
            $off=Read-PackU64 $idx ($large+$ix*8)
        }
        if($off -gt [uint64]$script:PackBound -or $off -lt 12){throw 'Pack offset outside supported range'}
        $map.Add($oid,[long]$off)
        $orders.Add([long]$off)
    }
    $packPath=[IO.Path]::ChangeExtension($IndexPath,'.pack')
    $pack=[IO.File]::ReadAllBytes($packPath)
    if($pack.Length -gt $script:PackBound -or $pack.Length -lt 32 -or
       $script:Ascii.GetString($pack,0,4) -cne 'PACK' -or
       (Read-PackU32 $pack 4) -notin @(2,3) -or (Read-PackU32 $pack 8) -ne $count){
        throw 'Unsupported/malformed Git pack header'
    }
    $tail=Get-PackHex (Get-PackSlice $pack ($pack.Length-20) 20)
    if((Get-PackSha (Get-PackSlice $pack 0 ($pack.Length-20))) -cne $tail){throw 'Pack checksum mismatch'}
    if($tail -cne (Get-PackHex (Get-PackSlice $idx ($idx.Length-40) 20))){throw 'Pack/index checksum disagreement'}
    $orders.Sort()
    for($i=0;$i -lt $orders.Count;$i++){
        if($orders[$i] -ge $pack.Length-20 -or ($i -gt 0 -and $orders[$i] -eq $orders[$i-1])){
            throw 'Duplicate or invalid packed object offset'
        }
    }
    return [pscustomobject]@{ Pack=$pack; IdToOffset=$map; OrderedOffsets=$orders }
}
function Get-PackInflated([byte[]]$B,[long]$Start,[long]$End){
    if($Start+6 -gt $End -or $End -gt $B.Length -or $B[$Start] -ne 0x78 -or
        (([int]$B[$Start]*256+[int]$B[$Start+1])%31) -ne 0 -or
        ($B[$Start+1] -band 32) -ne 0){throw 'Invalid packed zlib header'}
    $stream=[IO.MemoryStream]::new($B,[int]($Start+2),[int]($End-$Start-6),$false)
    $out=[IO.MemoryStream]::new()
    try{
        $def=[IO.Compression.DeflateStream]::new($stream,[IO.Compression.CompressionMode]::Decompress,$true)
        try{
            $buffer=New-Object byte[] 16384
            while(($n=$def.Read($buffer,0,$buffer.Length)) -gt 0){
                if($out.Length+$n -gt $script:ExpandBound){throw 'Packed decompression limit exceeded'}
                $out.Write($buffer,0,$n)
            }
        }finally{$def.Dispose()}
        $raw=$out.ToArray()
        if((Read-PackU32 $B ($End-4)) -ne (Get-PackAdler $raw)){throw 'Packed zlib Adler mismatch'}
        return ,$raw
    }finally{$stream.Dispose();$out.Dispose()}
}
function Read-PackAt([object]$C,[long]$Offset,[int]$Depth,[object]$Seen){
    if($Depth -gt 32 -or -not $Seen.Add($Offset)){throw 'Pack delta recursion/cycle exceeded'}
    try{
        $B=$C.Pack
        [long]$pos=$Offset
        if($pos -ge $B.Length-20){throw 'Pack entry offset truncated'}
        [int]$c=$B[$pos];$pos++
        $type=($c -shr 4) -band 7
        [long]$size=$c -band 15
        [int]$shift=4
        while(($c -band 128) -ne 0){
            if($pos -ge $B.Length-20 -or $shift -gt 49){throw 'Malformed pack entry header'}
            $c=[int]$B[$pos];$pos++
            $size=$size -bor ([long]($c -band 127) -shl $shift)
            $shift+=7
        }
        if($size -gt $script:ExpandBound){throw 'Packed object exceeds size bound'}
        [long]$baseOffset=-1
        $baseOid=$null
        if($type -eq 6){
            if($pos -ge $B.Length-20){throw 'Truncated OFS_DELTA base'}
            $c=[int]$B[$pos];$pos++
            [long]$distance=$c -band 127
            while(($c -band 128) -ne 0){
                if($pos -ge $B.Length-20){throw 'Truncated OFS_DELTA distance'}
                $c=[int]$B[$pos];$pos++
                $distance=(($distance+1) -shl 7) -bor ($c -band 127)
                if($distance -gt $Offset){throw 'Invalid OFS_DELTA back-reference'}
            }
            $baseOffset=$Offset-$distance
        }elseif($type -eq 7){
            $baseOid=Get-PackHex (Get-PackSlice $B $pos 20);$pos+=20
            if(-not $C.IdToOffset.ContainsKey($baseOid)){throw 'REF_DELTA base not in bounded pack'}
            $baseOffset=$C.IdToOffset[$baseOid]
        }elseif($type -notin @(1,2,3,4)){throw 'Unsupported Git packed object type'}
        $next=[long]($B.Length-20)
        foreach($candidate in $C.OrderedOffsets){if($candidate -gt $Offset){$next=$candidate;break}}
        $data=Get-PackInflated $B $pos $next
        if($data.Length -ne $size){throw 'Packed entry inflated length mismatch'}
        if($type -in @(6,7)){
            $base=Read-PackAt $C $baseOffset ($Depth+1) $Seen
            $typeName=$base.Type
            $data=Apply-PackDelta $base.Data $data
        }else{
            $typeName=@{1='commit';2='tree';3='blob';4='tag'}[$type]
        }
        return [pscustomobject]@{ Type=$typeName; Data=$data; Sha=(Get-PackObjectId $typeName $data) }
    }finally{$null=$Seen.Remove($Offset)}
}
function Get-GitLitePackedObject {
    [CmdletBinding()]param(
        [Parameter(Mandatory)][string]$RepositoryPath,
        [Parameter(Mandatory)][string]$Sha
    )
    if($Sha -cnotmatch '^[0-9a-f]{40}$'){throw 'Expected full lowercase SHA-1 object ID'}
    $root=[IO.Path]::GetFullPath($RepositoryPath)
    $git=[IO.Path]::Combine($root,'.git')
    if(-not [IO.Directory]::Exists($git)){throw 'Expected ordinary .git directory'}
    $p=[IO.Path]::Combine($git,'objects','pack')
    if(-not [IO.Directory]::Exists($p)){throw 'No Git pack directory'}
    $indices=@([IO.Directory]::GetFiles($p,'pack-*.idx'))
    if($indices.Count -gt 64){throw 'Too many packs for bounded reader'}
    foreach($f in $indices){
        $ctx=Open-PackContext $f
        if($ctx.IdToOffset.ContainsKey($Sha)){
            $seen=[System.Collections.Generic.HashSet[long]]::new()
            $answer=Read-PackAt $ctx $ctx.IdToOffset[$Sha] 0 $seen
            if($answer.Sha -cne $Sha){throw 'Packed object SHA-1 mismatch'}
            return $answer
        }
    }
    throw 'Object not present in any supported pack; loose-object lookup is separate'
}
Export-ModuleMember -Function Get-GitLitePackedObject
