[CmdletBinding()]
param(
    [Parameter()]
    [string]$OutputDirectory = (Join-Path $PWD '.local/topology-discovery'),

    [Parameter()]
    [string]$PublicOrganization,

    [Parameter()]
    [switch]$InstallMissing,

    [Parameter()]
    [switch]$RunPublicInventory
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

function Assert-Command {
    param([Parameter(Mandatory)][string]$Name)
    if (-not (Get-Command $Name -ErrorAction SilentlyContinue)) {
        throw "Required command '$Name' was not found on PATH."
    }
}

function Invoke-GhCapture {
    param(
        [Parameter(Mandatory)][string[]]$Arguments,
        [Parameter(Mandatory)][string]$OutputPath,
        [switch]$AllowFailure
    )

    $parent = Split-Path -Parent $OutputPath
    if ($parent) { New-Item -ItemType Directory -Force -Path $parent | Out-Null }

    $display = 'gh ' + (($Arguments | ForEach-Object {
        if ($_ -match '\s') { '"' + $_ + '"' } else { $_ }
    }) -join ' ')
    Write-Host "> $display"

    $previous = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try {
        $output = & gh @Arguments 2>&1 | ForEach-Object { $_.ToString() }
        $exitCode = $LASTEXITCODE
    }
    finally {
        $ErrorActionPreference = $previous
    }

    $output | Set-Content -LiteralPath $OutputPath -Encoding utf8
    if ($exitCode -ne 0 -and -not $AllowFailure) {
        throw "Command failed with exit code $exitCode. See $OutputPath"
    }

    [pscustomobject]@{
        Command = $display
        ExitCode = $exitCode
        OutputPath = $OutputPath
    }
}

Assert-Command gh
New-Item -ItemType Directory -Force -Path $OutputDirectory | Out-Null

$approvedExtensions = @(
    [pscustomobject]@{ Repository = 'mona-actions/gh-stats'; Command = 'stats' },
    [pscustomobject]@{ Repository = 'mona-actions/gh-repo-stats'; Command = 'repo-stats' },
    [pscustomobject]@{ Repository = 'mona-actions/gh-repo-map'; Command = 'repo-map' },
    [pscustomobject]@{ Repository = 'mona-actions/gh-pma'; Command = 'pma' },
    [pscustomobject]@{ Repository = 'mona-actions/gh-migration-validator'; Command = 'migration-validator' }
)

$authPath = Join-Path $OutputDirectory 'gh-auth-status.txt'
Invoke-GhCapture -Arguments @('auth', 'status') -OutputPath $authPath -AllowFailure | Out-Null

$extensionList = & gh extension list 2>$null | Out-String
$probeResults = [System.Collections.Generic.List[object]]::new()

foreach ($extension in $approvedExtensions) {
    $installed = $extensionList -match [regex]::Escape($extension.Repository)

    if (-not $installed -and $InstallMissing) {
        Write-Host "Installing approved extension $($extension.Repository)"
        & gh extension install $extension.Repository
        if ($LASTEXITCODE -ne 0) {
            Write-Warning "Unable to install $($extension.Repository); continuing probe."
        }
        $extensionList = & gh extension list 2>$null | Out-String
        $installed = $extensionList -match [regex]::Escape($extension.Repository)
    }

    $helpPath = Join-Path $OutputDirectory ("help-{0}.txt" -f $extension.Command)
    if ($installed) {
        $probe = Invoke-GhCapture -Arguments @($extension.Command, '--help') -OutputPath $helpPath -AllowFailure
        $probeResults.Add([pscustomobject]@{
            repository = $extension.Repository
            command = $extension.Command
            installed = $true
            help_exit_code = $probe.ExitCode
            help_output = $helpPath
        })
    }
    else {
        $probeResults.Add([pscustomobject]@{
            repository = $extension.Repository
            command = $extension.Command
            installed = $false
            help_exit_code = $null
            help_output = $null
        })
    }
}

$probeResults |
    ConvertTo-Json -Depth 5 |
    Set-Content -LiteralPath (Join-Path $OutputDirectory 'extension-probe.json') -Encoding utf8

if ($RunPublicInventory) {
    if ([string]::IsNullOrWhiteSpace($PublicOrganization)) {
        throw '-RunPublicInventory requires -PublicOrganization. Use only an explicitly public-safe organization.'
    }

    # gh-stats supports a dry-run specifically intended to estimate collection/API behavior.
    if (($probeResults | Where-Object { $_.command -eq 'stats' }).installed) {
        Invoke-GhCapture \
            -Arguments @('stats', '--org', $PublicOrganization, '--dry-run') \
            -OutputPath (Join-Path $OutputDirectory "gh-stats-$PublicOrganization-dry-run.txt") \
            -AllowFailure | Out-Null
    }

    # gh-repo-stats is retained as the simpler migration-inventory baseline.
    # Help output is always captured first because option names can evolve between versions.
    Write-Host 'Public inventory execution beyond gh-stats dry-run is intentionally not automated yet.'
    Write-Host 'Review captured help/contracts before adding collector-specific invocation.'
}

Write-Host "Topology discovery probe complete. Local output: $OutputDirectory"
Write-Host 'Do not commit unsanitized private discovery output to this public repository.'
