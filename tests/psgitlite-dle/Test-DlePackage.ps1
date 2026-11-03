param([Parameter(Mandatory)][ValidateSet('build','smoke')][string]$Mode)
# Synthetic clean-room deployment of a source-only PowerShell distribution.
# The product itself never invokes Git, external interpreters, or network.
Set-StrictMode -Version Latest
$ErrorActionPreference='Stop'
function Assert([bool]$Ok,[string]$Label){
  if(!$Ok){throw ('FAIL '+$Label)}
  Write-Output ('PASS '+$Label)
}
$root=[IO.Path]::Combine($env:RUNNER_TEMP,'psgitlite-dle-distribution')
$files=@(
  'psgitlite-native/PSGitLiteCore.psm1',
  'psgitlite-dle/PSGitLiteDle.psm1',
  'psgitlite-dle/Invoke-GitLiteDle.ps1',
  'psgitlite-dle/Invoke-DleHandoffObserve.ps1',
  'psgitlite-dle/PSGitLiteRecoveryV2.psm1',
  'psgitlite-dle/Invoke-DleSafeInspect.ps1'
)
if($Mode -eq 'build'){
  if([IO.Directory]::Exists($root)){throw 'DLE_PACKAGE_ALREADY_EXISTS'}
  [void][IO.Directory]::CreateDirectory($root)
  $spec=@()
  foreach($relative in $files){
    $source=Join-Path (Split-Path $PSScriptRoot -Parent) $relative
    $dest=Join-Path $root $relative
    [void][IO.Directory]::CreateDirectory([IO.Path]::GetDirectoryName($dest))
    [IO.File]::Copy($source,$dest)
    $hash=(Get-FileHash -LiteralPath $dest -Algorithm SHA256).Hash.ToLowerInvariant()
    $size=([IO.FileInfo]::new($dest)).Length
    $spec+=@([ordered]@{path=$relative.Replace('\','/');sha256=$hash;bytes=$size})
  }
  $manifest=[ordered]@{schemaVersion='psgitlite.dle-distribution.v2';
    runtime='Windows PowerShell 5.1 or PowerShell 7';
    nativeGitRequired=$false;networkRequired=$false;adminRequired=$false;
    files=$spec}
  $json=(ConvertTo-Json -InputObject $manifest -Depth 6 -Compress)+[char]10
  [IO.File]::WriteAllText((Join-Path $root 'manifest.json'),$json,[Text.UTF8Encoding]::new($false))
  Assert ([IO.File]::Exists((Join-Path $root 'manifest.json'))) 'content-addressed source-only package manifest'
  Write-Output 'PSGITLITE_DLE_PACKAGE_BUILD_PASS'
}
else{
  $manifestPath=Join-Path $root 'manifest.json'
  $manifest=[IO.File]::ReadAllText($manifestPath)|ConvertFrom-Json
  Assert ($manifest.schemaVersion -ceq 'psgitlite.dle-distribution.v2' -and $manifest.files.Count -eq 6) 'clean package manifest schema'
  foreach($file in $manifest.files){
    $path=[IO.Path]::Combine($root,$file.path.Replace('/',[IO.Path]::DirectorySeparatorChar))
    $hash=(Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash.ToLowerInvariant()
    Assert ($hash -ceq $file.sha256 -and ([IO.FileInfo]::new($path)).Length -eq $file.bytes) ('immutable source package hash '+$file.path)
  }
  $cli=[IO.Path]::Combine($root,'psgitlite-dle','Invoke-GitLiteDle.ps1')
  $target=[IO.Path]::Combine($env:RUNNER_TEMP,'psgitlite-dle-cleanroom')
  $oldPath=$env:PATH
  try{
    $env:PATH=''
    Assert (-not (Get-Command git -ErrorAction SilentlyContinue)) 'clean-room package has no Git executable'
    $init=(& $cli -Command Init -RepositoryPath $target -OutputFormat Json)|ConvertFrom-Json
    Assert (!$init.Existing) 'fresh module deployment initializes standalone Git repo'
    $result=(& $cli -Command Checkpoint -RepositoryPath $target -WorksetId install -RequestId packaged01 -StepId startup -Phase Verify -Status VERIFIED -Message 'Packaged DLE source smoke' -NextBaton 'Continue after fresh PowerShell interpreter' -OutputFormat Json)|ConvertFrom-Json
    Assert ($result.Head -cmatch '^[0-9a-f]{40}$') 'packaged module commits checkpoint'
    $snapshot=(& $cli -Command Inspect -RepositoryPath $target -WorksetId install -OutputFormat Json)|ConvertFrom-Json
    Assert ($snapshot.Head -ceq $result.Head -and $snapshot.Recovery -ceq 'CONTINUE_FROM_BATON') 'clean-room module verifies checkpoint without Git'
    $module=Join-Path $root 'psgitlite-dle/PSGitLiteDle.psm1'
    $safeCli=Join-Path $root 'psgitlite-dle/Invoke-DleSafeInspect.ps1'
    Import-Module $module -Force
    $targetV2=Join-Path $env:RUNNER_TEMP 'psgitlite-v2-cleanroom'
    $null=Initialize-GitLiteDle -RepositoryPath $targetV2
    $intent=New-GitLiteDleCheckpoint -RepositoryPath $targetV2 -WorksetId packagedv2 -RequestId pkg-intent -StepId syntheticeffect -Phase Apply -Status INTENT -Message 'synthetic packaged v2 intent' -NextBaton 'reconcile synthetic fixture' -SchemaVariant v2 -EventKind EXTERNAL_EFFECT -EffectId pkg-effect
    $unresolved=(& $safeCli -RepositoryPath $targetV2 -WorksetId packagedv2 -Format Json)|ConvertFrom-Json
    Assert ($unresolved.verdict -ceq 'RECONCILE_REQUIRED' -and !$unresolved.autoReexecuteAllowed) 'packaged v2 full-history assessor refuses pending effect'
    $verified=New-GitLiteDleCheckpoint -RepositoryPath $targetV2 -WorksetId packagedv2 -RequestId pkg-verified -StepId syntheticeffect -Phase Verify -Status VERIFIED -Message 'synthetic packaged verification' -NextBaton 'continue checked synthetic work' -ExpectedHead $intent.Head -SchemaVariant v2 -EventKind EXTERNAL_EFFECT -EffectId pkg-effect -EvidenceRefs @('fixture:synthetic-verified')
    $resolved=(& $safeCli -RepositoryPath $targetV2 -WorksetId packagedv2 -Format Json)|ConvertFrom-Json
    Assert ($resolved.verdict -ceq 'CONTINUE_FROM_BATON' -and $resolved.head -ceq $verified.Head -and !$resolved.autoReexecuteAllowed) 'packaged v2 effectId verification and safe read'

  }finally{$env:PATH=$oldPath}
  Write-Output 'PSGITLITE_DLE_PACKAGE_SMOKE_PASS'
}
