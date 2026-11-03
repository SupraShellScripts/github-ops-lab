# Public-only differential qualification of Git packfiles.
# Product under test uses ONLY PowerShell and built-in .NET.
# git.exe is a fixture creator / independent oracle, never invoked by product.
Set-StrictMode -Version Latest
$ErrorActionPreference='Stop'
Import-Module (Join-Path $PSScriptRoot 'PSGitLitePack.psm1') -Force

function Assert([bool]$Value,[string]$Name) {
    if(-not $Value){throw "FAIL $Name"}
    Write-Output "PASS $Name"
}
function Invoke-Oracle([string]$Root,[string[]]$Arg){
    $out=@(& git -C $Root @Arg 2>&1)
    if($LASTEXITCODE -ne 0){throw "Oracle failure: $($Arg -join ' '): $($out -join '; ')"}
    return ,([string[]]$out)
}
$root=[IO.Path]::Combine([IO.Path]::GetTempPath(),'psgitlite-packed-'+[guid]::NewGuid().ToString('N'))
[void][IO.Directory]::CreateDirectory($root)
try{
    $null=Invoke-Oracle $root @('init','-b','main')
    $null=Invoke-Oracle $root @('config','user.email','synthetic@example.invalid')
    $null=Invoke-Oracle $root @('config','user.name','Synthetic Git Tester')
    $p=[IO.Path]::Combine($root,'shared.txt')
    $b=[IO.Path]::Combine($root,'binary.bin')
    [IO.File]::WriteAllBytes($b,[byte[]]@(0,1,255,0,10,127,0,128))
    for($i=0;$i -lt 40;$i++){
        $body=('common fixture data:' + ('X'*16000) + ' delta-marker-' + $i + [char]10)
        [IO.File]::WriteAllBytes($p,[Text.Encoding]::UTF8.GetBytes($body))
        $null=Invoke-Oracle $root @('add','shared.txt')
        if($i -eq 0){$null=Invoke-Oracle $root @('add','binary.bin')}
        $null=Invoke-Oracle $root @('commit','-m',('synthetic-'+$i))
    }
    $null=Invoke-Oracle $root @('branch','feature/synthetic')
    $null=Invoke-Oracle $root @('gc','--aggressive','--prune=now')
    $packDir=[IO.Path]::Combine($root,'.git','objects','pack')
    $idx=@([IO.Directory]::GetFiles($packDir,'*.idx'))
    Assert ($idx.Count -eq 1) 'synthetic fixture consolidated into one pack'
    $verify=Invoke-Oracle $root @('verify-pack','-v',$idx[0])
    $deltas=@($verify | Where-Object {$_ -match '^[0-9a-f]{40}\s+\w+\s+\d+\s+\d+\s+\d+\s+\d+\s+[0-9a-f]{40}$'})
    Assert ($deltas.Count -gt 0) 'independent Git produced real deltas'
    $records=Invoke-Oracle $root @('rev-list','--objects','--all')
    $hashes=[System.Collections.Generic.HashSet[string]]::new([StringComparer]::Ordinal)
    foreach($r in $records){if($r -match '^([0-9a-f]{40})'){$null=$hashes.Add($Matches[1])}}
    Assert ($hashes.Count -ge 100) 'full Git object graph identified'
    $objects=0
    foreach($oid in $hashes){
        $expectedType=(Invoke-Oracle $root @('cat-file','-t',$oid))[0]
        $expectedSize=[int](Invoke-Oracle $root @('cat-file','-s',$oid))[0]
        $read=Get-GitLitePackedObject -RepositoryPath $root -Sha $oid
        if($read.Type -cne $expectedType -or $read.Sha -cne $oid -or $read.Data.Length -ne $expectedSize){
            throw "FAIL packed object differential: $oid"
        }
        $objects++
    }
    Assert ($objects -eq $hashes.Count) 'all packed commits trees blobs roundtrip against Git'
    $first=($hashes | Select-Object -First 1)
    $old=$env:PATH
    try{
        $env:PATH=''
        Assert (-not (Get-Command git -ErrorAction SilentlyContinue)) 'git executable unavailable to product'
        $read=Get-GitLitePackedObject -RepositoryPath $root -Sha $first
        Assert ($read.Sha -ceq $first) 'pack object works without git executable'
    }finally{$env:PATH=$old}
    Import-Module (Join-Path $PSScriptRoot 'PSGitLiteRefs.psm1') -Force
    $branches=@(Get-GitLiteBranches -RepositoryPath $root)
    Assert ($branches.Count -eq 2 -and @($branches|Where-Object{$_.Current}).Count -eq 1) 'packed and loose branch refs recognized'
    Assert (($branches | Where-Object{$_.Branch -eq 'feature/synthetic'}).Count -ge 1) 'feature branch listed'
    $log=@(Get-GitLiteFirstParentLog -RepositoryPath $root -MaxCount 10)
    $gitLog=@(Invoke-Oracle $root @('rev-list','--first-parent','--max-count=10','HEAD'))
    Assert ($log.Count -eq 10 -and $gitLog.Count -eq 10) 'first-parent history count'
    for($i=0;$i -lt 10;$i++){if($log[$i].Sha -cne $gitLog[$i]){throw 'Git first-parent history mismatch'}}
    Assert $true 'first-parent SHA history matches native Git'
    $rejected=$false
    try{$null=@(Get-GitLiteFirstParentLog -RepositoryPath $root -Ref '../escape')}catch{$rejected=$true}
    Assert $rejected 'malformed Git ref refused'
    $shaBytes=[IO.File]::ReadAllBytes($idx[0])
    $shaBytes[$shaBytes.Length-1]=[byte]($shaBytes[$shaBytes.Length-1] -bxor 1)
    [IO.File]::SetAttributes($idx[0],[IO.FileAttributes]::Normal)
    [IO.File]::WriteAllBytes($idx[0],$shaBytes)
    $rejected=$false
    try{$null=Get-GitLitePackedObject -RepositoryPath $root -Sha $first}catch{$rejected=$true}
    Assert $rejected 'tampered .idx checksum refused'
    Write-Output ('PSGITLITE_PACK_PASS count='+$objects+' deltas='+$deltas.Count+' PowerShell='+$PSVersionTable.PSVersion)
}finally{
    if([IO.Directory]::Exists($root)){
        foreach($f in [IO.Directory]::EnumerateFiles($root,'*',[IO.SearchOption]::AllDirectories)){
            [IO.File]::SetAttributes($f,[IO.FileAttributes]::Normal)
        }
        [IO.Directory]::Delete($root,$true)
    }
}
