[CmdletBinding()]
param(
    [Parameter()]
    [string]$Root = $PWD
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$rootPath = [IO.Path]::GetFullPath($Root)
$patterns = @(
    @{ Name = 'private-repository-reference'; Regex = '(?i)\b[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]*-private(?:#\d+)?\b' },
    @{ Name = 'private-repository-url'; Regex = '(?i)github\.com/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]*-private(?:/(?:issues|pull)/\d+)?' },
    @{ Name = 'private-control-plane-label'; Regex = '(?im)^\s*(governance authority|private authority|private source of truth)\s*:' }
)

$extensions = @('.md','.txt','.yml','.yaml','.json','.ps1','.py','.js','.ts','.toml')
$skipDirs = @('.git','.local','node_modules','vendor')
$findings = [System.Collections.Generic.List[object]]::new()

Get-ChildItem -LiteralPath $rootPath -Recurse -File | ForEach-Object {
    $file = $_
    if ($extensions -notcontains $file.Extension.ToLowerInvariant()) { return }
    $relative = [IO.Path]::GetRelativePath($rootPath,$file.FullName)
    $parts = $relative -split '[\\/]'
    if (@($parts | Where-Object { $skipDirs -contains $_ }).Count -gt 0) { return }

    $text = Get-Content -LiteralPath $file.FullName -Raw
    foreach ($pattern in $patterns) {
        foreach ($match in [regex]::Matches($text,$pattern.Regex)) {
            $line = 1 + ($text.Substring(0,$match.Index) -split "`n").Count - 1
            $findings.Add([pscustomobject]@{
                path = $relative
                line = $line
                rule = $pattern.Name
                match = $match.Value
            })
        }
    }
}

if ($findings.Count -gt 0) {
    $findings | Sort-Object path,line,rule | Format-Table -AutoSize | Out-String | Write-Host
    throw "Public-boundary validation failed with $($findings.Count) finding(s)."
}

Write-Host 'PASS: no private-repository/control-plane reference patterns detected.'
