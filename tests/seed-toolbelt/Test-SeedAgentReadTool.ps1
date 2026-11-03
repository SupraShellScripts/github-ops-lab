# Public-original synthetic agent tool contract tests. No network/credentials.
Set-StrictMode -Version Latest
$ErrorActionPreference='Stop'
$wrapper=Join-Path $PSScriptRoot 'Invoke-SeedAgentReadTool.ps1'
$checks=0
function Check([string]$Name,[bool]$Pass){
    $script:checks++
    if(-not $Pass){throw ('FAIL '+$script:checks+' '+$Name)}
    Write-Output ('PASS '+$script:checks+' '+$Name)
}
$root=Join-Path ([IO.Path]::GetTempPath()) ('seedagent-'+[guid]::NewGuid().ToString('N'))
$inputFile=Join-Path $root 'input.json'
$outputFile=Join-Path $root 'output.json'
$contextFile=Join-Path $root 'context.json'
function SetContext([string]$Role='Development'){
    @{provenance=@{environmentRole=$Role}} | ConvertTo-Json -Depth 8 |
        Set-Content -LiteralPath $script:contextFile -Encoding UTF8
}
function Call($Arguments){
    @{input=@{workflowInput=$Arguments}} | ConvertTo-Json -Depth 8 |
        Set-Content -LiteralPath $script:inputFile -Encoding UTF8
    if(Test-Path -LiteralPath $script:outputFile){Remove-Item -LiteralPath $script:outputFile -Force}
    $null=& $script:wrapper -InputPath $script:inputFile -OutputPath $script:outputFile -ContextPath $script:contextFile
    return (Get-Content -LiteralPath $script:outputFile -Raw | ConvertFrom-Json)
}
function Reject([string]$Name,$Arguments,[string]$Reason){
    $match=$false
    try{$null=Call $Arguments}
    catch{$match=([string]$_.Exception.Message -ceq ('SEED-AGENT-'+$Reason))}
    Check $Name $match
}
try{
    $null=New-Item -ItemType Directory -Path $root -Force
    SetContext
    $a=Call @{operation='observe'}
    Check 'A01-observe' ($a.status -ceq 'OBSERVED_NO_SOURCE_CHANGE')
    Check 'A02-untrusted-observation' ($a.result.git -ceq 'NOT_PROVEN')
    $a=Call @{operation='inventory'}
    Check 'A03-fixed-synthetic-inventory' ($a.result.files.Count -eq 5)
    $a=Call @{operation='inspect';relativePath='sample.json'}
    Check 'A04-json-metadata-only' ($a.result.format -ceq 'json' -and
        $null -eq $a.result.PSObject.Properties['content'])
    $a=Call @{operation='inspect';relativePath='sample.xml'}
    Check 'A05-xml-root' ($a.result.rootElement -ceq 'items')
    $a=Call @{operation='inspect';relativePath='sample.md'}
    Check 'A06-markdown-heading' ($a.result.headings.Count -eq 3)
    $a=Call @{operation='inspect';relativePath='sample.txt'}
    Check 'A07-text-lines' ($a.result.lineCount -gt 2)
    $a=Call @{operation='find';relativePath='sample.txt';needle='NEEDLE'}
    Check 'A08-bounded-literal-find' ($a.result.matches.Count -eq 1 -and
        $null -eq $a.result.matches[0].PSObject.Properties['excerpt'])
    $a=Call @{operation='syntax'}
    Check 'A09-bounded-PowerShell-parse' ($a.result.parses -and -not $a.result.executed)
    $a=Call @{operation='plan';task='Improve synthetic tool'}
    Check 'A10-plan-only' ($a.result.admission -ceq 'PLAN_ONLY')
    Check 'A11-no-tool-registration' (-not $a.toolRegistered -and -not $a.applied)
    Reject 'A12-traversal-not-admitted' @{operation='inspect';relativePath='../outside.json'} 'UNCLASSIFIED'
    Reject 'A13-unexpected-model-approval' @{operation='observe';approval='yes'} 'UNEXPECTED_ARGUMENT'
    Reject 'A14-unknown-operation' @{operation='execute'} 'UNKNOWN_OPERATION'
    Reject 'A15-content-flag-not-admitted' @{operation='inspect';relativePath='sample.json';includeContent='true'} 'UNEXPECTED_ARGUMENT'
    SetContext 'Deployment'
    Reject 'A16-deployment-not-admitted' @{operation='observe'} 'CONTEXT_ROLE_NOT_ADMITTED'
    SetContext
    $a=Call @{operation='inventory'}
    $text=($a|ConvertTo-Json -Depth 15 -Compress)
    Check 'A17-no-host-credential-serialization' ($text -notmatch 'OPENROUTER_API_KEY|Authorization|Bearer ')
    Check 'A18-no-raw-file-content' ($text -notmatch 'Safe XML without DTD|NEEDLE|synthetic tool')
    Write-Output ('SEED_AGENT_TOOL_PASS assertions='+$script:checks+' shell='+$PSVersionTable.PSVersion.ToString())
}
finally{if(Test-Path -LiteralPath $root){Remove-Item -LiteralPath $root -Recurse -Force}}
