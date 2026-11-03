# PSGitLite read-only SHA-1 refs and first-parent history.
# Requires sibling PSGitLitePack.psm1. PS5.1 + built-in .NET only.
Set-StrictMode -Version Latest
$ErrorActionPreference='Stop'
Import-Module (Join-Path $PSScriptRoot 'PSGitLitePack.psm1') -Force

function Assert-LiteRefName([string]$Name) {
    if([string]::IsNullOrWhiteSpace($Name) -or $Name.Length -gt 300 -or
       $Name -notmatch '^[a-zA-Z0-9._/-]+$' -or $Name.Contains('..') -or
       $Name.Contains('//') -or $Name.StartsWith('/') -or $Name.EndsWith('/') -or
       $Name.StartsWith('.') -or $Name.EndsWith('.') -or $Name.Contains('/.')){
       throw 'Unsafe Git ref name'
    }
}
function Get-LiteRefStore([string]$RepositoryPath) {
    $root=[IO.Path]::GetFullPath($RepositoryPath)
    $git=[IO.Path]::Combine($root,'.git')
    if(-not [IO.Directory]::Exists($git)){throw 'Expected non-bare Git repository'}
    $configPath=[IO.Path]::Combine($git,'config')
    if(-not [IO.File]::Exists($configPath)){throw 'Git config missing'}
    $config=[IO.File]::ReadAllText($configPath)
    if($config -match '(?im)^\s*objectFormat\s*=\s*sha256\b' -or
       $config -match '(?im)^\s*repositoryformatversion\s*=\s*[1-9]'){
        throw 'Unsupported Git repository format'
    }
    $refs=[System.Collections.Generic.Dictionary[string,string]]::new([StringComparer]::Ordinal)
    $packed=[IO.Path]::Combine($git,'packed-refs')
    if([IO.File]::Exists($packed)){
        foreach($line in [IO.File]::ReadAllLines($packed)){
            if($line.Length -eq 0 -or $line[0] -eq '#' -or $line[0] -eq '^'){continue}
            if($line -match '^([0-9a-f]{40}) refs/heads/(.+)$'){
                $name=$Matches[2];Assert-LiteRefName $name
                if($refs.ContainsKey($name)){throw 'Duplicate packed branch ref'}
                $refs[$name]=$Matches[1]
            }
        }
    }
    $heads=[IO.Path]::Combine($git,'refs','heads')
    if([IO.Directory]::Exists($heads)){
        foreach($file in [IO.Directory]::GetFiles($heads,'*',[IO.SearchOption]::AllDirectories)){
            $name=$file.Substring($heads.Length+1).Replace([IO.Path]::DirectorySeparatorChar,'/')
            Assert-LiteRefName $name
            $sha=[IO.File]::ReadAllText($file).Trim()
            if($sha -cnotmatch '^[0-9a-f]{40}$'){throw 'Unsupported or invalid loose branch ref'}
            $refs[$name]=$sha
        }
    }
    $head=[IO.File]::ReadAllText([IO.Path]::Combine($git,'HEAD')).Trim()
    $current=$null
    if($head -cmatch '^ref: refs/heads/(.+)$'){
        $current=$Matches[1];Assert-LiteRefName $current
    }elseif($head -cnotmatch '^[0-9a-f]{40}$'){
        throw 'Invalid HEAD'
    }
    return [pscustomobject]@{Root=$root;Git=$git;Refs=$refs;Current=$current;Detached=if(!$current){$head}else{$null}}
}
function Get-GitLiteBranches {
    [CmdletBinding()]param([Parameter(Mandatory)][string]$RepositoryPath)
    $state=Get-LiteRefStore $RepositoryPath
    foreach($name in @($state.Refs.Keys | Sort-Object)){
        [pscustomobject]@{Branch=$name;Commit=$state.Refs[$name];Current=($state.Current -ceq $name)}
    }
}
function Get-GitLiteFirstParentLog {
    [CmdletBinding()]param([Parameter(Mandatory)][string]$RepositoryPath,
        [string]$Ref='HEAD',[ValidateRange(1,1000)][int]$MaxCount=20)
    $state=Get-LiteRefStore $RepositoryPath
    if($Ref -ceq 'HEAD'){
        if($state.Current){$Ref=$state.Current}else{$Ref=$state.Detached}
    }
    if($Ref -cmatch '^[0-9a-f]{40}$'){$oid=$Ref}
    else{
        Assert-LiteRefName $Ref
        if(!$state.Refs.ContainsKey($Ref)){throw 'Unknown branch ref'}
        $oid=$state.Refs[$Ref]
    }
    $seen=[System.Collections.Generic.HashSet[string]]::new([StringComparer]::Ordinal)
    $utf8=[Text.UTF8Encoding]::new($false,$true)
    for($i=0;$i -lt $MaxCount -and $oid;$i++){
        if(!$seen.Add($oid)){throw 'Cyclic Git commit ancestry'}
        $object=Get-GitLitePackedObject -RepositoryPath $state.Root -Sha $oid
        if($object.Type -cne 'commit'){throw 'Reference did not point at commit'}
        $txt=$utf8.GetString($object.Data)
        $sep=$txt.IndexOf(([char]10).ToString()+[char]10)
        if($sep -lt 0){throw 'Malformed Git commit header'}
        $header=$txt.Substring(0,$sep)
        $message=$txt.Substring($sep+2)
        $parent=$null;$tree=$null;$author=$null
        foreach($line in $header.Split([char]10)){
            if($line -match '^tree ([0-9a-f]{40})$'){$tree=$Matches[1]}
            elseif($line -match '^parent ([0-9a-f]{40})$' -and !$parent){$parent=$Matches[1]}
            elseif($line.StartsWith('author ')){$author=$line.Substring(7)}
        }
        if(!$tree -or !$author){throw 'Incomplete Git commit'}
        [pscustomobject]@{Sha=$oid;Parent=$parent;Tree=$tree;Author=$author;Message=$message}
        $oid=$parent
    }
}
Export-ModuleMember -Function Get-GitLiteBranches,Get-GitLiteFirstParentLog
