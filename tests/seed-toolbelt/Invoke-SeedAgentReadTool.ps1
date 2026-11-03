#requires -Version 5.1
<#
  Public-original read-only agent tool adapter. InputPath/OutputPath/ContextPath
  are supplied by the trusted workflow host, never by model tool arguments.
  The model can only inspect bundled synthetic fixtures, never arbitrary host
  files, and cannot execute/build/register tools or send network requests.
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory=$true)][string]$InputPath,
    [Parameter(Mandatory=$true)][string]$OutputPath,
    [Parameter(Mandatory=$true)][string]$ContextPath
)
Set-StrictMode -Version 2.0
$ErrorActionPreference='Stop'
Import-Module (Join-Path $PSScriptRoot 'SeedToolbelt.psm1') -Force -ErrorAction Stop
function Deny([string]$Code){throw ('SEED-AGENT-'+$Code)}
function ReadJson([string]$Path){
    if(-not (Test-Path -LiteralPath $Path -PathType Leaf)){Deny 'INPUT_NOT_FOUND'}
    $f=Get-Item -LiteralPath $Path -Force -ErrorAction Stop
    if($f.Length -lt 2 -or $f.Length -gt 16384 -or
       ($f.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0){Deny 'INPUT_NOT_ADMITTED'}
    try{return (Get-Content -LiteralPath $Path -Raw -ErrorAction Stop | ConvertFrom-Json -ErrorAction Stop)}
    catch{Deny 'BAD_INPUT_JSON'}
}
$context=ReadJson $ContextPath
if($null -eq $context.provenance -or
   @('Development','Test') -cnotcontains [string]$context.provenance.environmentRole){
    Deny 'CONTEXT_ROLE_NOT_ADMITTED'
}
$request=ReadJson $InputPath
if($null -eq $request.input -or $null -eq $request.input.workflowInput){Deny 'MISSING_TOOL_ARGUMENTS'}
$arguments=$request.input.workflowInput
$allowed=@('operation','relativePath','format','needle','task')
foreach($property in $arguments.PSObject.Properties){
    if($allowed -cnotcontains [string]$property.Name -or
       $property.Value -isnot [string]){Deny 'UNEXPECTED_ARGUMENT'}
}
$op=[string]$arguments.operation
$fixtures=Join-Path $PSScriptRoot 'fixtures'
if(-not (Test-Path -LiteralPath $fixtures -PathType Container)){Deny 'FIXTURES_MISSING'}
switch($op){
    'observe'{
        if(@($arguments.PSObject.Properties).Count -ne 1){Deny 'EXTRA_ARGUMENT'}
        $observation=Get-SeedObservation
    }
    'inventory'{
        if(@($arguments.PSObject.Properties).Count -ne 1){Deny 'EXTRA_ARGUMENT'}
        $observation=Get-SeedInventory -Root $fixtures -Paths @('sample.json','sample.txt','sample.md','sample.xml','sample.ps1')
    }
    'inspect'{
        if(@($arguments.PSObject.Properties).Count -gt 3 -or
           [string]::IsNullOrWhiteSpace($arguments.relativePath)){Deny 'MISSING_DOCUMENT'}
        $format=if($null -ne $arguments.PSObject.Properties['format']){[string]$arguments.format}else{'Auto'}
        if(@('Auto','Json','Xml','Text','Markdown') -cnotcontains $format){Deny 'BAD_DOCUMENT_FORMAT'}
        $observation=Get-SeedDocument -Root $fixtures -RelativePath ([string]$arguments.relativePath) -Format $format
    }
    'find'{
        if(@($arguments.PSObject.Properties).Count -ne 3 -or
           [string]::IsNullOrWhiteSpace($arguments.relativePath) -or
           [string]::IsNullOrWhiteSpace($arguments.needle)){Deny 'MISSING_FIND_ARGUMENT'}
        $observation=Find-SeedLiteral -Root $fixtures -RelativePath ([string]$arguments.relativePath) -Needle ([string]$arguments.needle)
    }
    'syntax'{
        if(@($arguments.PSObject.Properties).Count -ne 1){Deny 'EXTRA_ARGUMENT'}
        $document=Get-SeedDocument -Root $fixtures -RelativePath 'sample.ps1' -Format Text -IncludeContent
        $observation=Test-SeedPowerShellSource -Source ([string]$document.content)
    }
    'plan'{
        if(@($arguments.PSObject.Properties).Count -ne 2 -or
           [string]::IsNullOrWhiteSpace($arguments.task)){Deny 'MISSING_TASK'}
        $observation=New-SeedAgentPlan -Task ([string]$arguments.task)
    }
    default{Deny 'UNKNOWN_OPERATION'}
}
$out=[ordered]@{
    schemaVersion='seed.agent-tool-response.v1'
    status='OBSERVED_NO_SOURCE_CHANGE'
    scope='BUNDLED_SYNTHETIC_FIXTURES_ONLY'
    applied=$false
    toolRegistered=$false
    result=$observation
}
$parent=Split-Path -Parent $OutputPath
if(-not (Test-Path -LiteralPath $parent -PathType Container) -or
   [IO.Path]::GetExtension($OutputPath) -cne '.json'){Deny 'OUTPUT_NOT_ADMITTED'}
$out | ConvertTo-Json -Depth 16 | Set-Content -LiteralPath $OutputPath -Encoding UTF8 -ErrorAction Stop
