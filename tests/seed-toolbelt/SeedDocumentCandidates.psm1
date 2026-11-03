#requires -Version 5.1
<#
  Public-original source-neutral document creation/change candidates.
  No file writing, model calls, execution, network or automatic approval.
  JSON/XML parsing is syntax validation, not a schema or safety attestation.
#>
Set-StrictMode -Version 2.0
function Deny-SeedDoc([string]$Code){throw ('SEED-DOC-'+$Code)}
function Get-SeedDocHash([byte[]]$Bytes){
    $sha=[Security.Cryptography.SHA256]::Create()
    try{return [BitConverter]::ToString($sha.ComputeHash($Bytes)).Replace('-','').ToLowerInvariant()}
    finally{$sha.Dispose()}
}
function Assert-SeedDocPath([string]$Relative,[string]$Format){
    if([string]::IsNullOrWhiteSpace($Relative) -or $Relative.Length -gt 240 -or
       $Relative -notmatch '^[\p{L}\p{N}_ ./-]+$' -or $Relative.Contains('\') -or
       $Relative.Contains('//') -or $Relative.Contains(':') -or $Relative.StartsWith('/')){
        Deny-SeedDoc 'UNSAFE_RELATIVE_PATH'
    }
    foreach($part in $Relative.Split('/')){
        if($part -eq '' -or $part -eq '.' -or $part -eq '..' -or
           $part.EndsWith('.') -or $part.EndsWith(' ') -or
           $part -match '^(?i:CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\..*)?$'){
            Deny-SeedDoc 'UNSAFE_PATH_SEGMENT'
        }
    }
    $extensions=@{Json='.json';Text='.txt';Markdown='.md';Xml='.xml'}
    if([IO.Path]::GetExtension($Relative).ToLowerInvariant() -cne $extensions[$Format]){
        Deny-SeedDoc 'FORMAT_EXTENSION_MISMATCH'
    }
}
function Assert-SeedDocumentSyntax([string]$Format,[string]$Content){
    if($Content.Contains([char]0)){Deny-SeedDoc 'EMBEDDED_NUL'}
    if($Content -match '[\x01-\x08\x0B\x0C\x0E-\x1F]'){Deny-SeedDoc 'CONTROL_CHARACTER'}
    switch($Format){
        'Json'{
            try{$null=ConvertFrom-Json -InputObject $Content -ErrorAction Stop}
            catch{Deny-SeedDoc 'INVALID_JSON'}
        }
        'Xml'{
            $settings=[Xml.XmlReaderSettings]::new()
            $settings.DtdProcessing=[Xml.DtdProcessing]::Prohibit
            $settings.XmlResolver=$null
            $settings.MaxCharactersInDocument=1048576
            $src=[IO.StringReader]::new($Content)
            $reader=$null
            try{
                $reader=[Xml.XmlReader]::Create($src,$settings)
                $doc=[Xml.XmlDocument]::new()
                $doc.XmlResolver=$null
                $doc.Load($reader)
                if($null -eq $doc.DocumentElement){Deny-SeedDoc 'XML_MISSING_ROOT'}
            }catch{
                if([string]$_.Exception.Message -cmatch '^SEED-DOC-'){throw}
                Deny-SeedDoc 'INVALID_XML'
            }finally{
                if($null -ne $reader){$reader.Dispose()}
                $src.Dispose()
            }
        }
        'Markdown'{
            # Not rendering; Markdown may contain unsafe HTML or links.
            # Downstream renderers must sandbox/sanitize independently.
        }
        'Text'{
            # Strict UTF-8 and the bounded byte budget are checked by caller.
        }
    }
}
function New-SeedDocumentChangeCandidate {
    [CmdletBinding()]param(
        [Parameter(Mandatory=$true)][string]$TargetRelativePath,
        [Parameter(Mandatory=$true)][ValidateSet('Json','Text','Markdown','Xml')][string]$Format,
        [Parameter(Mandatory=$true)][AllowEmptyString()][string]$Content,
        [string]$ExpectedOldSha256
    )
    Assert-SeedDocPath -Relative $TargetRelativePath -Format $Format
    $utf8=[Text.UTF8Encoding]::new($false,$true)
    try{$bytes=$utf8.GetBytes($Content)}catch{Deny-SeedDoc 'UTF8_ENCODING_FAILED'}
    if($bytes.Length -lt 1 -or $bytes.Length -gt 1048576){Deny-SeedDoc 'DOCUMENT_SIZE_NOT_ADMITTED'}
    Assert-SeedDocumentSyntax -Format $Format -Content $Content
    $operation='create'
    if(-not [string]::IsNullOrWhiteSpace($ExpectedOldSha256)){
        if($ExpectedOldSha256 -cnotmatch '^[0-9a-f]{64}$'){Deny-SeedDoc 'INVALID_OLD_HASH'}
        $operation='replace'
    }
    return [pscustomobject][ordered]@{
        schemaVersion='seed.document-change-candidate.v1'
        operation=$operation
        targetRelativePath=$TargetRelativePath
        targetAuthority='CALLER_SELECTED_NOT_AUTHENTICATED'
        format=$Format.ToLowerInvariant()
        oldSha256=if($operation -ceq 'replace'){$ExpectedOldSha256}else{$null}
        newSha256=(Get-SeedDocHash -Bytes $bytes)
        bytes=$bytes.Length
        newContentBase64=[Convert]::ToBase64String($bytes)
        status='UNTRUSTED_DOCUMENT_CANDIDATE_NO_WRITES'
        approved=$false
        applied=$false
        nextGate='INDEPENDENT_CHANGE_GRANT_PATH_POLICY_AND_POST_WRITE_VERIFY'
        validation=if($Format -ceq 'Xml'){'DTD_PROHIBITED_NO_EXTERNAL_RESOLVER'}elseif($Format -ceq 'Json'){'SYNTAX_ONLY_DUPLICATE_KEYS_UNATTESTED'}else{'BYTES_ONLY_NOT_RENDERER_SAFE'}
    }
}
function Test-SeedDocumentChangeCandidate {
    [CmdletBinding()]param([Parameter(Mandatory=$true)]$Candidate)
    if([string]$Candidate.schemaVersion -cne 'seed.document-change-candidate.v1' -or
       [string]$Candidate.status -cne 'UNTRUSTED_DOCUMENT_CANDIDATE_NO_WRITES' -or
       $Candidate.approved -ne $false -or $Candidate.applied -ne $false){
        Deny-SeedDoc 'CANDIDATE_NOT_UNTRUSTED'
    }
    if([string]$Candidate.newContentBase64 -cnotmatch '^[A-Za-z0-9+/]+={0,2}$'){
        Deny-SeedDoc 'BAD_BASE64'
    }
    try{$bytes=[Convert]::FromBase64String([string]$Candidate.newContentBase64)}
    catch{Deny-SeedDoc 'BAD_BASE64'}
    if($bytes.Length -ne [int]$Candidate.bytes -or
       (Get-SeedDocHash -Bytes $bytes) -cne [string]$Candidate.newSha256){
        Deny-SeedDoc 'CANDIDATE_HASH_MISMATCH'
    }
    $utf8=[Text.UTF8Encoding]::new($false,$true)
    try{$content=$utf8.GetString($bytes)}catch{Deny-SeedDoc 'INVALID_UTF8'}
    $fmt=([string]$Candidate.format)
    $case=@{json='Json';text='Text';markdown='Markdown';xml='Xml'}
    if(-not $case.ContainsKey($fmt)){Deny-SeedDoc 'UNKNOWN_FORMAT'}
    $rebuilt=New-SeedDocumentChangeCandidate -TargetRelativePath ([string]$Candidate.targetRelativePath) -Format $case[$fmt] -Content $content -ExpectedOldSha256 ([string]$Candidate.oldSha256)
    if($rebuilt.operation -cne [string]$Candidate.operation){Deny-SeedDoc 'OPERATION_MISMATCH'}
    return [pscustomobject]@{
        schemaVersion='seed.document-change-verification.v1'
        status='CANDIDATE_HASH_AND_SYNTAX_MATCH_NOT_APPROVED'
        sha256=$rebuilt.newSha256
        applied=$false
    }
}
Export-ModuleMember -Function New-SeedDocumentChangeCandidate,Test-SeedDocumentChangeCandidate
