#requires -Version 5.1
<#
  Public-original, no-Git PowerShell seed toolkit for an agent runtime.
  All operations are read-only or return an UNTRUSTED candidate in memory.
  No tool execution, registration, provider request, privileges or file writes.
#>
Set-StrictMode -Version 2.0
function Deny-Seed([string]$Code){throw ('SEED-'+$Code)}
function Get-SeedHash([byte[]]$Bytes){
    $sha=[Security.Cryptography.SHA256]::Create()
    try{return [BitConverter]::ToString($sha.ComputeHash($Bytes)).Replace('-','').ToLowerInvariant()}
    finally{$sha.Dispose()}
}
function Get-SeedUtf8([string]$Value){
    return ,([Text.UTF8Encoding]::new($false,$true)).GetBytes($Value)
}
function Get-SeedObservation {
    [CmdletBinding()]param()
    return [pscustomobject][ordered]@{
        schemaVersion='seed.observation.v1'
        shell='PowerShell'
        version=[string]$PSVersionTable.PSVersion
        languageMode=[string]$ExecutionContext.SessionState.LanguageMode
        nativeJson=[bool](Get-Command ConvertFrom-Json -ErrorAction SilentlyContinue)
        nativeXml=$true
        nativeParser=$true
        fileWrite='NOT_PROVEN'
        childProcess='NOT_PROVEN'
        network='NOT_PROVEN'
        git='NOT_PROVEN'
        sourceAuthority='NOT_PROVEN'
    }
}
function Resolve-SeedFile {
    [CmdletBinding()]param(
        [Parameter(Mandatory=$true)][string]$Root,
        [Parameter(Mandatory=$true)][string]$RelativePath
    )
    if([string]::IsNullOrWhiteSpace($RelativePath) -or $RelativePath.Length -gt 240 -or
       $RelativePath -notmatch '^[\p{L}\p{N}_ ./-]+$' -or
       $RelativePath.Contains('\') -or $RelativePath.Contains('//') -or
       $RelativePath.Contains(':') -or $RelativePath.StartsWith('/')){
        Deny-Seed 'INVALID_PATH'
    }
    foreach($part in $RelativePath.Split('/')){
        if($part -eq '' -or $part -eq '.' -or $part -eq '..' -or
           $part.EndsWith(' ') -or $part.EndsWith('.') -or
           $part -match '^(?i:CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\..*)?$'){
            Deny-Seed 'INVALID_PATH'
        }
    }
    if(-not (Test-Path -LiteralPath $Root -PathType Container)){Deny-Seed 'ROOT_NOT_FOUND'}
    $base=[IO.Path]::GetFullPath($Root).TrimEnd([char[]]@('/','\'))
    $target=[IO.Path]::GetFullPath((Join-Path $base $RelativePath.Replace('/',[IO.Path]::DirectorySeparatorChar)))
    $cmp=if([IO.Path]::DirectorySeparatorChar -eq '\'){[StringComparison]::OrdinalIgnoreCase}else{[StringComparison]::Ordinal}
    if(-not $target.StartsWith($base+[IO.Path]::DirectorySeparatorChar,$cmp)){Deny-Seed 'OUTSIDE_ROOT'}
    if(-not (Test-Path -LiteralPath $target -PathType Leaf)){Deny-Seed 'FILE_NOT_FOUND'}
    $cursor=$target
    while($true){
        $node=Get-Item -LiteralPath $cursor -Force -ErrorAction Stop
        if(($node.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0){Deny-Seed 'REPARSE_DENIED'}
        if($cursor.Equals($base,$cmp)){break}
        $parent=[IO.Directory]::GetParent($cursor)
        if($null -eq $parent){Deny-Seed 'OUTSIDE_ROOT'}
        $cursor=$parent.FullName
    }
    return $target
}
function Read-SeedUtf8File {
    param([string]$Root,[string]$RelativePath)
    $path=Resolve-SeedFile -Root $Root -RelativePath $RelativePath
    $item=Get-Item -LiteralPath $path -Force -ErrorAction Stop
    if($item.Length -gt 1048576){Deny-Seed 'FILE_TOO_LARGE'}
    $bytes=[IO.File]::ReadAllBytes($path)
    if($bytes.Length -gt 1048576){Deny-Seed 'FILE_TOO_LARGE'}
    try{$text=([Text.UTF8Encoding]::new($false,$true)).GetString($bytes)}
    catch{Deny-Seed 'NOT_UTF8'}
    if($text.Length -gt 0 -and $text[0] -eq [char]0xFEFF){$text=$text.Substring(1)}
    return [pscustomobject]@{text=$text;sha256=(Get-SeedHash $bytes);byteCount=$bytes.Length}
}
function Get-SeedInventory {
    [CmdletBinding()]param([string]$Root,[string[]]$Paths)
    if($Paths.Count -lt 1 -or $Paths.Count -gt 32){Deny-Seed 'INVENTORY_COUNT'}
    $seen=[Collections.Generic.HashSet[string]]::new([StringComparer]::OrdinalIgnoreCase)
    $items=New-Object System.Collections.ArrayList
    foreach($path in $Paths){
        if(-not $seen.Add($path)){Deny-Seed 'DUPLICATE_PATH'}
        $file=Read-SeedUtf8File -Root $Root -RelativePath $path
        $null=$items.Add([pscustomobject]@{path=$path;sha256=$file.sha256;byteCount=$file.byteCount})
    }
    return [pscustomobject]@{schemaVersion='seed.inventory.v1';files=@($items.ToArray());authority='LOCAL_OBSERVATION_ONLY'}
}
function Get-SeedDocument {
    [CmdletBinding()]param(
        [Parameter(Mandatory=$true)][string]$Root,
        [Parameter(Mandatory=$true)][string]$RelativePath,
        [ValidateSet('Auto','Json','Text','Markdown','Xml')][string]$Format='Auto',
        [switch]$IncludeContent
    )
    $file=Read-SeedUtf8File -Root $Root -RelativePath $RelativePath
    if($Format -eq 'Auto'){
        switch([IO.Path]::GetExtension($RelativePath).ToLowerInvariant()){
            '.json'{$Format='Json'}'.xml'{$Format='Xml'}'.md'{$Format='Markdown'}
            '.markdown'{$Format='Markdown'}default{$Format='Text'}
        }
    }
    $meta=[ordered]@{
        schemaVersion='seed.document.v1'
        format=$Format.ToLowerInvariant()
        sha256=$file.sha256
        byteCount=$file.byteCount
        contentReturned=[bool]$IncludeContent
    }
    switch($Format){
        'Json'{
            try{$obj=ConvertFrom-Json -InputObject $file.text -ErrorAction Stop}
            catch{Deny-Seed 'JSON_PARSE_FAILED'}
            $kind=if($null -eq $obj){'null'}elseif($obj -is [array]){'array'}elseif($obj -is [pscustomobject]){'object'}else{'scalar'}
            $meta['kind']=$kind
            $meta['validation']='PARSE_ONLY_DUPLICATE_KEYS_NOT_PROVEN'
            if($IncludeContent){$meta['content']=$obj}
        }
        'Xml'{
            $settings=[Xml.XmlReaderSettings]::new()
            $settings.DtdProcessing=[Xml.DtdProcessing]::Prohibit
            $settings.XmlResolver=$null
            $settings.MaxCharactersInDocument=1048576
            $source=[IO.StringReader]::new($file.text)
            $reader=$null
            try{
                $reader=[Xml.XmlReader]::Create($source,$settings)
                $doc=[Xml.XmlDocument]::new()
                $doc.XmlResolver=$null
                $doc.Load($reader)
                if($null -eq $doc.DocumentElement){Deny-Seed 'XML_NO_ROOT'}
                $meta['rootElement']=$doc.DocumentElement.LocalName
                $meta['validation']='DTD_PROHIBITED_RESOLVER_DISABLED'
                if($IncludeContent){$meta['content']=$file.text}
            }catch{
                if([string]$_.Exception.Message -cmatch '^SEED-'){throw}
                Deny-Seed 'XML_PARSE_FAILED'
            }finally{
                if($null -ne $reader){$reader.Dispose()}
                $source.Dispose()
            }
        }
        'Markdown'{
            $lines=[regex]::Split($file.text,"\r\n|\n|\r")
            $headings=New-Object System.Collections.ArrayList
            $fence=$false
            foreach($line in $lines){
                if($line -match '^\s{0,3}([\x60]{3,}|~{3,})'){$fence=-not $fence;continue}
                if(-not $fence -and $line -match '^\s{0,3}(#{1,6})\s+(.+?)\s*$'){
                    $null=$headings.Add([pscustomobject]@{level=$matches[1].Length;title=$matches[2]})
                    if($headings.Count -ge 64){break}
                }
            }
            $meta['lineCount']=$lines.Length
            $meta['headings']=@($headings.ToArray())
            $meta['validation']='HEADING_SCAN_NOT_FULL_MARKDOWN_PARSER'
            if($IncludeContent){$meta['content']=$file.text}
        }
        'Text'{
            $meta['lineCount']=([regex]::Split($file.text,"\r\n|\n|\r")).Length
            $meta['validation']='STRICT_UTF8'
            if($IncludeContent){$meta['content']=$file.text}
        }
    }
    return [pscustomobject]$meta
}
function Find-SeedLiteral {
    [CmdletBinding()]param(
        [string]$Root,[string]$RelativePath,
        [Parameter(Mandatory=$true)][string]$Needle,
        [ValidateRange(1,100)][int]$MaxHits=20,
        [switch]$IncludeExcerpts
    )
    if($Needle.Length -lt 1 -or $Needle.Length -gt 128 -or
       $Needle.Contains([char]10) -or $Needle.Contains([char]13)){Deny-Seed 'INVALID_NEEDLE'}
    $file=Read-SeedUtf8File -Root $Root -RelativePath $RelativePath
    $lines=[regex]::Split($file.text,"\r\n|\n|\r")
    $hits=New-Object System.Collections.ArrayList
    for($i=0;$i -lt $lines.Length;$i++){
        $index=$lines[$i].IndexOf($Needle,[StringComparison]::OrdinalIgnoreCase)
        if($index -ge 0){
            $row=[ordered]@{line=$i+1;column=$index+1}
            if($IncludeExcerpts){$row['excerpt']=$lines[$i].Substring(0,[Math]::Min(256,$lines[$i].Length))}
            $null=$hits.Add([pscustomobject]$row)
            if($hits.Count -ge $MaxHits){break}
        }
    }
    return [pscustomobject]@{
        schemaVersion='seed.find.v1'
        sha256=$file.sha256
        matches=@($hits.ToArray())
        contentReturned=[bool]$IncludeExcerpts
        search='LITERAL_ONLY'
    }
}
function Test-SeedPowerShellSource {
    [CmdletBinding()]param([Parameter(Mandatory=$true)][AllowEmptyString()][string]$Source)
    $bytes=Get-SeedUtf8 $Source
    if($bytes.Length -gt 65536){Deny-Seed 'SOURCE_TOO_LARGE'}
    $tokens=$null;$errors=$null
    $ast=[Management.Automation.Language.Parser]::ParseInput($Source,[ref]$tokens,[ref]$errors)
    $commands=@($ast.FindAll({
        param($node)
        return ($node -is [Management.Automation.Language.CommandAst])
    },$true))
    $dynamic=@($commands | Where-Object {$null -eq $_.GetCommandName()}).Count
    return [pscustomobject]@{
        schemaVersion='seed.syntax.v1'
        sha256=(Get-SeedHash $bytes)
        parses=(@($errors).Count -eq 0)
        errorCount=@($errors).Count
        commands=$commands.Count
        dynamicCommands=$dynamic
        safety='NOT_PROVEN_AST_SYNTAX_ONLY'
        executed=$false
    }
}
function New-SeedToolCandidate {
    [CmdletBinding()]param(
        [Parameter(Mandatory=$true)][string]$Name,
        [Parameter(Mandatory=$true)][string]$ScriptText,
        [Parameter(Mandatory=$true)][string]$TestText,
        [ValidateSet('read-only','workspace-write','external-write')][string]$DeclaredEffect='read-only'
    )
    if($Name -cnotmatch '^[a-z][a-z0-9_-]{2,63}$'){Deny-Seed 'INVALID_TOOL_NAME'}
    $script=Test-SeedPowerShellSource -Source $ScriptText
    $test=Test-SeedPowerShellSource -Source $TestText
    if(-not $script.parses -or -not $test.parses){Deny-Seed 'INVALID_SOURCE_SYNTAX'}
    return [pscustomobject]@{
        schemaVersion='seed.tool-candidate.v1'
        name=$Name
        claimedEffect=$DeclaredEffect
        scriptSha256=$script.sha256
        testSha256=$test.sha256
        scriptBase64=[Convert]::ToBase64String((Get-SeedUtf8 $ScriptText))
        testBase64=[Convert]::ToBase64String((Get-SeedUtf8 $TestText))
        status='UNTRUSTED_CANDIDATE_NOT_INSTALLED'
        approved=$false
        registered=$false
        executed=$false
        nextGate='INDEPENDENT_SIGNED_GRANT_REVIEW_NATIVE_TEST_HASH_PIN'
    }
}
function New-SeedAgentPlan {
    [CmdletBinding()]param([Parameter(Mandatory=$true)][string]$Task,[string[]]$Needed=@())
    if([string]::IsNullOrWhiteSpace($Task) -or $Task.Length -gt 1024){Deny-Seed 'INVALID_TASK'}
    if($Needed.Count -gt 16){Deny-Seed 'TOO_MANY_CAPABILITIES'}
    return [pscustomobject]@{
        schemaVersion='seed.plan.v1'
        task=$Task
        phases=@('Discover','Observe','Plan','Apply','Verify')
        needed=@($Needed)
        admission='PLAN_ONLY'
        required='INDEPENDENT_APPROVAL_CAPABILITY_PROOF_NATIVE_VERIFY'
    }
}
Export-ModuleMember -Function Get-SeedObservation,Resolve-SeedFile,Get-SeedInventory,Get-SeedDocument,Find-SeedLiteral,Test-SeedPowerShellSource,New-SeedToolCandidate,New-SeedAgentPlan
