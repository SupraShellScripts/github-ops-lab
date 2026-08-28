param([string]$Name = 'world')

$items = @('WindowsPowerShell51', 'PowerShell7')
foreach ($item in $items) {
    Write-Output ("{0}: hello {1}" -f $item, $Name)
}
