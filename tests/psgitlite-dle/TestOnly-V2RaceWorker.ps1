param(
  [Parameter(Mandatory)][string]$RepositoryPath,
  [Parameter(Mandatory)][string]$ExpectedHead,
  [Parameter(Mandatory)][ValidateRange(1,2)][int]$Index
)
# Public synthetic child process; test harness only, NOT product runtime.
Set-StrictMode -Version Latest
$ErrorActionPreference='Stop'
Import-Module (Join-Path $PSScriptRoot 'PSGitLiteDle.psm1') -Force
try{
  $receipt=New-GitLiteDleCheckpoint -RepositoryPath $RepositoryPath -WorksetId racev2 -RequestId ('race-'+$Index) -StepId race -Phase Verify -Status VERIFIED -Message ('synthetic racing writer '+$Index) -NextBaton 'Inspect winning checkpoint' -ExpectedHead $ExpectedHead -SchemaVariant v2 -EventKind CHECKPOINT
  Write-Output (ConvertTo-Json -InputObject $receipt -Depth 5 -Compress)
  exit 0
}catch{
  [Console]::Error.WriteLine('V2_RACE_CHILD_REFUSED '+$_.Exception.Message)
  exit 2
}
