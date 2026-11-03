# Public-original, synthetic, no network/credentials/Git. Windows PS5.1 and pwsh.
Set-StrictMode -Version Latest
$ErrorActionPreference='Stop'
Import-Module (Join-Path $PSScriptRoot 'SeedToolbelt.psm1') -Force
$script:checks=0
function Check([string]$Label,[bool]$Condition){
    $script:checks++
    if(-not $Condition){throw ('FAIL '+$script:checks+' '+$Label)}
    Write-Output ('PASS '+$script:checks+' '+$Label)
}
function Reject([string]$Label,[scriptblock]$Call,[string]$Category){
    $denied=$false
    try{$null= & $Call}
    catch{$denied=([string]$_.Exception.Message -ceq ('SEED-'+$Category))}
    Check $Label $denied
}
function WriteUtf8([string]$Path,[string]$Value){
    $dir=Split-Path -Parent $Path
    $null=New-Item -ItemType Directory -Path $dir -Force
    [IO.File]::WriteAllBytes($Path,([Text.UTF8Encoding]::new($false,$true)).GetBytes($Value))
}
$root=Join-Path ([IO.Path]::GetTempPath()) ('seedtools-'+[guid]::NewGuid().ToString('N'))
$utf8=[Text.UTF8Encoding]::new($false,$true)
try{
    $null=New-Item -ItemType Directory -Path $root -Force
    WriteUtf8 (Join-Path $root 'data.json') '{"language":"Thai","count":2}'
    WriteUtf8 (Join-Path $root 'data.xml') '<items><item>Thai</item></items>'
    WriteUtf8 (Join-Path $root 'doc.md') ('# Heading'+[char]10+'Some text'+[char]10+'## Second'+[char]10)
    WriteUtf8 (Join-Path $root 'content.txt') ('first'+[char]10+'One MARK'+[char]10+'last'+[char]10)
    $thaiName=([string][char]0x0E20)+([char]0x0E32)+([char]0x0E29)+([char]0x0E32)+'.txt'
    $thaiText=([string][char]0x0E2A)+([char]0x0E27)+([char]0x0E31)+([char]0x0E2A)+([char]0x0E14)+([char]0x0E35)
    WriteUtf8 (Join-Path $root $thaiName) ($thaiText+[char]10)
    $observation=Get-SeedObservation
    Check '01-observation-schema' ($observation.schemaVersion -ceq 'seed.observation.v1')
    Check '02-never-proves-Git' ($observation.git -ceq 'NOT_PROVEN')
    Check '03-never-proves-network' ($observation.network -ceq 'NOT_PROVEN')
    Check '04-observed-version' (-not [string]::IsNullOrEmpty($observation.version))
    $p=New-SeedAgentPlan -Task 'Improve the local tool catalog' -Needed @('nativeParser','json')
    Check '05-DOPAV-phases' ($p.phases.Count -eq 5 -and $p.phases[0] -ceq 'Discover' -and $p.phases[4] -ceq 'Verify')
    Check '06-plan-does-not-authorize' ($p.admission -ceq 'PLAN_ONLY')
    $inventory=Get-SeedInventory -Root $root -Paths @('data.json','content.txt')
    Check '07-file-inventory' ($inventory.files.Count -eq 2 -and $inventory.files[0].sha256 -cmatch '^[a-f0-9]{64}$')
    Check '08-inventory-untrusted-provenance' ($inventory.authority -ceq 'LOCAL_OBSERVATION_ONLY')
    $json=Get-SeedDocument -Root $root -RelativePath 'data.json'
    Check '09-json-autodetect' ($json.format -ceq 'json' -and $json.kind -ceq 'object')
    Check '10-default-no-raw-json' ($null -eq $json.PSObject.Properties['content'])
    $json=Get-SeedDocument -Root $root -RelativePath 'data.json' -IncludeContent
    Check '11-explicit-json-content' ($json.content.count -eq 2 -and $json.contentReturned)
    $xml=Get-SeedDocument -Root $root -RelativePath 'data.xml'
    Check '12-xml-safe-root' ($xml.rootElement -ceq 'items')
    Check '13-no-raw-xml-default' ($null -eq $xml.PSObject.Properties['content'])
    $md=Get-SeedDocument -Root $root -RelativePath 'doc.md'
    Check '14-markdown-headings' ($md.headings.Count -eq 2 -and $md.headings[1].level -eq 2)
    $txt=Get-SeedDocument -Root $root -RelativePath 'content.txt'
    Check '15-text-line-count' ($txt.lineCount -eq 4)
    $thai=Get-SeedDocument -Root $root -RelativePath $thaiName -IncludeContent
    Check '16-Thai-Unicode-read' ($thai.content -ceq ($thaiText+[char]10))
    $found=Find-SeedLiteral -Root $root -RelativePath 'content.txt' -Needle 'mark'
    Check '17-case-insensitive-literal-find' ($found.matches.Count -eq 1 -and $found.matches[0].line -eq 2)
    Check '18-no-excerpt-default' (-not $found.contentReturned -and $null -eq $found.matches[0].PSObject.Properties['excerpt'])
    $found=Find-SeedLiteral -Root $root -RelativePath 'content.txt' -Needle 'MARK' -IncludeExcerpts
    Check '19-explicit-excerpt' ($found.matches[0].excerpt -cmatch 'MARK')
    Reject '20-traversal-denied' {Get-SeedDocument -Root $root -RelativePath '../external.txt'} 'INVALID_PATH'
    Reject '21-ADS-denied' {Get-SeedDocument -Root $root -RelativePath 'content.txt:secret'} 'INVALID_PATH'
    Reject '22-duplicate-file-denied' {Get-SeedInventory -Root $root -Paths @('data.json','DATA.JSON')} 'DUPLICATE_PATH'
    Reject '23-regex-special-needle-invalid' {Find-SeedLiteral -Root $root -RelativePath 'content.txt' -Needle ([char]10)} 'INVALID_NEEDLE'
    WriteUtf8 (Join-Path $root 'broken.json') '{"x":}'
    Reject '24-json-syntax-denied' {Get-SeedDocument -Root $root -RelativePath 'broken.json'} 'JSON_PARSE_FAILED'
    WriteUtf8 (Join-Path $root 'xxe.xml') '<!DOCTYPE x [<!ENTITY ext SYSTEM "file:///tmp/synthetic">]><x>&ext;</x>'
    Reject '25-XML-DTD-XXE-denied' {Get-SeedDocument -Root $root -RelativePath 'xxe.xml'} 'XML_PARSE_FAILED'
    [IO.File]::WriteAllBytes((Join-Path $root 'bad.txt'),[byte[]]@(255,254,255))
    Reject '26-invalid-UTF8-denied' {Get-SeedDocument -Root $root -RelativePath 'bad.txt'} 'NOT_UTF8'
    [IO.File]::WriteAllBytes((Join-Path $root 'big.txt'),(New-Object byte[] 1048577))
    Reject '27-bounded-read' {Get-SeedDocument -Root $root -RelativePath 'big.txt'} 'FILE_TOO_LARGE'
    $parsed=Test-SeedPowerShellSource -Source 'Write-Output "hello"'
    Check '28-AST-syntax-only' ($parsed.parses -and -not $parsed.executed -and $parsed.safety -ceq 'NOT_PROVEN_AST_SYNTAX_ONLY')
    $invalid=Test-SeedPowerShellSource -Source 'Write-Output ('
    Check '29-AST-syntax-error' (-not $invalid.parses -and $invalid.errorCount -gt 0)
    $candidate=New-SeedToolCandidate -Name 'seed_echo' -ScriptText 'Write-Output "hello"' -TestText 'if($true){Write-Output "pass"}'
    Check '30-tool-candidate-created' ($candidate.scriptSha256 -cmatch '^[0-9a-f]{64}$')
    Check '31-tool-never-registered' (-not $candidate.registered -and -not $candidate.approved -and -not $candidate.executed)
    Check '32-tool-has-source-and-test' ($candidate.scriptBase64.Length -gt 0 -and $candidate.testBase64.Length -gt 0)
    Reject '33-invalid-source-tool-denied' {
        New-SeedToolCandidate -Name 'seed_echo' -ScriptText 'Write-Output (' -TestText 'Write-Output "pass"'
    } 'INVALID_SOURCE_SYNTAX'
    Reject '34-invalid-tool-name' {
        New-SeedToolCandidate -Name '../etc' -ScriptText 'Write-Output 1' -TestText 'Write-Output 2'
    } 'INVALID_TOOL_NAME'
    Check '35-input-content-unchanged' (([IO.File]::ReadAllText((Join-Path $root 'data.json'),$utf8)) -ceq '{"language":"Thai","count":2}')
    Write-Output ('SEED_TOOLBELT_PASS assertions='+$script:checks+' pwsh='+$PSVersionTable.PSVersion.ToString())
}
finally{if(Test-Path -LiteralPath $root){Remove-Item -LiteralPath $root -Recurse -Force}}
