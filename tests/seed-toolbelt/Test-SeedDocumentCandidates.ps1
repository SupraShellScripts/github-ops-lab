# Public-original synthetic document candidate tests; no file modifications.
Set-StrictMode -Version Latest
$ErrorActionPreference='Stop'
Import-Module (Join-Path $PSScriptRoot 'SeedDocumentCandidates.psm1') -Force
$script:checks=0
function Check([string]$Label,[bool]$Pass){
    $script:checks++
    if(-not $Pass){throw ('FAIL '+$script:checks+' '+$Label)}
    Write-Output ('PASS '+$script:checks+' '+$Label)
}
function Reject([string]$Label,[scriptblock]$Block,[string]$Reason){
    $denied=$false
    try{$null=& $Block}catch{$denied=([string]$_.Exception.Message -ceq ('SEED-DOC-'+$Reason))}
    Check $Label $denied
}
$json=New-SeedDocumentChangeCandidate -TargetRelativePath 'draft.json' -Format Json -Content '{"ok":true}'
Check 'D01-JSON-create-candidate' ($json.operation -ceq 'create' -and $json.format -ceq 'json')
Check 'D02-JSON-candidate-verified' ((Test-SeedDocumentChangeCandidate -Candidate $json).status -ceq 'CANDIDATE_HASH_AND_SYNTAX_MATCH_NOT_APPROVED')
Check 'D03-JSON-no-write' (-not $json.approved -and -not $json.applied)
$xml=New-SeedDocumentChangeCandidate -TargetRelativePath 'draft.xml' -Format Xml -Content '<items><item>ok</item></items>'
Check 'D04-XML-safe-created' ($xml.validation -ceq 'DTD_PROHIBITED_NO_EXTERNAL_RESOLVER')
Check 'D05-XML-signed-body-verified' ((Test-SeedDocumentChangeCandidate -Candidate $xml).sha256 -ceq $xml.newSha256)
$text=New-SeedDocumentChangeCandidate -TargetRelativePath 'draft.txt' -Format Text -Content 'synthetic text'
Check 'D06-text-created' ($text.bytes -eq 14)
$md=New-SeedDocumentChangeCandidate -TargetRelativePath 'draft.md' -Format Markdown -Content '# Synthetic'
Check 'D07-Markdown-created-not-rendered' ($md.format -ceq 'markdown' -and $md.validation -ceq 'BYTES_ONLY_NOT_RENDERER_SAFE')
$old=('a'*64)
$replacement=New-SeedDocumentChangeCandidate -TargetRelativePath 'draft.md' -Format Markdown -Content '# Updated' -ExpectedOldSha256 $old
Check 'D08-replace-binds-old-hash' ($replacement.operation -ceq 'replace' -and $replacement.oldSha256 -ceq $old)
Check 'D09-replace-hash-verified' ((Test-SeedDocumentChangeCandidate -Candidate $replacement).sha256 -ceq $replacement.newSha256)
Reject 'D10-invalid-JSON' {New-SeedDocumentChangeCandidate -TargetRelativePath 'draft.json' -Format Json -Content '{"x":}'} 'INVALID_JSON'
Reject 'D11-XXE-prohibited' {
    New-SeedDocumentChangeCandidate -TargetRelativePath 'draft.xml' -Format Xml -Content '<!DOCTYPE x [<!ENTITY xxe SYSTEM "file:///x">]><x>&xxe;</x>'
} 'INVALID_XML'
Reject 'D12-malformed-XML' {New-SeedDocumentChangeCandidate -TargetRelativePath 'draft.xml' -Format Xml -Content '<x>'} 'INVALID_XML'
Reject 'D13-path-traversal' {New-SeedDocumentChangeCandidate -TargetRelativePath '../draft.json' -Format Json -Content '{}'} 'UNSAFE_PATH_SEGMENT'
Reject 'D14-extension-mismatch' {New-SeedDocumentChangeCandidate -TargetRelativePath 'draft.ps1' -Format Text -Content 'x'} 'FORMAT_EXTENSION_MISMATCH'
Reject 'D15-embedded-NUL' {New-SeedDocumentChangeCandidate -TargetRelativePath 'draft.txt' -Format Text -Content ('a'+[char]0+'b')} 'EMBEDDED_NUL'
Reject 'D16-invalid-old-hash' {New-SeedDocumentChangeCandidate -TargetRelativePath 'draft.txt' -Format Text -Content 'hi' -ExpectedOldSha256 'bad'} 'INVALID_OLD_HASH'
$changed=$json|ConvertTo-Json -Depth 12|ConvertFrom-Json
$changed.newSha256=('f'*64)
Reject 'D17-tampered-digest' {Test-SeedDocumentChangeCandidate -Candidate $changed} 'CANDIDATE_HASH_MISMATCH'
$changed=$json|ConvertTo-Json -Depth 12|ConvertFrom-Json
$changed.newContentBase64='not-base64$$'
Reject 'D18-tampered-base64' {Test-SeedDocumentChangeCandidate -Candidate $changed} 'BAD_BASE64'
$changed=$json|ConvertTo-Json -Depth 12|ConvertFrom-Json
$changed.approved=$true
Reject 'D19-model-approval-field-not-admitted' {Test-SeedDocumentChangeCandidate -Candidate $changed} 'CANDIDATE_NOT_UNTRUSTED'
Reject 'D20-bounded-size' {New-SeedDocumentChangeCandidate -TargetRelativePath 'draft.txt' -Format Text -Content ('a'*1048577)} 'DOCUMENT_SIZE_NOT_ADMITTED'
$thai=([string][char]0x0E2A)+([char]0x0E27)+([char]0x0E31)+([char]0x0E2A)+([char]0x0E14)+([char]0x0E35)
$thaiCandidate=New-SeedDocumentChangeCandidate -TargetRelativePath 'draft.txt' -Format Text -Content $thai
Check 'D21-UTF8-Thai-content' ($thaiCandidate.bytes -gt $thai.Length)
Check 'D22-UTF8-hash-verified' ((Test-SeedDocumentChangeCandidate -Candidate $thaiCandidate).sha256 -ceq $thaiCandidate.newSha256)
Write-Output ('SEED_DOCUMENT_CANDIDATE_PASS assertions='+$script:checks+' shell='+$PSVersionTable.PSVersion.ToString())
