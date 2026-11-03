#requires -Version 5.1
[CmdletBinding()]param()
Set-StrictMode -Version 2.0
$ErrorActionPreference='Stop'
$java=Get-Command java -CommandType Application -ErrorAction Stop|Select-Object -First 1
$root=Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$out=Join-Path $root 'artifacts/bounded-safety'
$null=New-Item -ItemType Directory -Path $out -Force
$jar=Join-Path $out 'tla2tools-1.7.4.jar'
$expected='936a262061c914694dfd669a543be24573c45d5aa0ff20a8b96b23d01e050e88'
Invoke-WebRequest -UseBasicParsing -Uri 'https://github.com/tlaplus/tlaplus/releases/download/v1.7.4/tla2tools.jar' -OutFile $jar -TimeoutSec 60
if((Get-FileHash $jar -Algorithm SHA256).Hash.ToLowerInvariant() -cne $expected){throw 'TLC_HASH_MISMATCH'}
$checks=New-Object Collections.ArrayList
foreach($model in @('RegistryBinding','CreateRecovery')){
 foreach($variant in @('safe','unsafe')){
  $source=Join-Path $PSScriptRoot ($model+'.tla')
  $config=Join-Path $PSScriptRoot ($model+'.'+$variant+'.cfg')
  $meta=Join-Path $out ([guid]::NewGuid().ToString('N'))
  $psi=New-Object Diagnostics.ProcessStartInfo
  $psi.FileName=$java.Source;$psi.UseShellExecute=$false;$psi.CreateNoWindow=$true
  $psi.RedirectStandardOutput=$true;$psi.RedirectStandardError=$true
  $psi.Arguments='-Xmx512m -jar "'+$jar+'" -workers 1 -seed 1 -metadir "'+$meta+'" -config "'+$config+'" "'+$source+'"'
  $p=[Diagnostics.Process]::Start($psi)
  try{
   $stdout=$p.StandardOutput.ReadToEndAsync();$stderr=$p.StandardError.ReadToEndAsync()
   if(-not $p.WaitForExit(60000)){$p.Kill();$p.WaitForExit();throw 'TLC_DEADLINE'}
   $log=$stdout.Result+[Environment]::NewLine+$stderr.Result
   $log|Set-Content (Join-Path $out ($model+'.'+$variant+'.log')) -Encoding UTF8
   $counterexample=$log -match 'Invariant Safety is violated'
   $passed=if($variant -ceq 'safe'){$p.ExitCode -eq 0 -and $log -match 'Model checking completed. No error has been found'}else{$p.ExitCode -ne 0 -and $counterexample}
   $states=$null;if($log -match '(\d+) distinct states found'){$states=[long]$matches[1]}
   $null=$checks.Add([ordered]@{model=$model;variant=$variant;passed=$passed;exitCode=$p.ExitCode;expectedCounterexample=$counterexample;distinctStates=$states;modelSha256=(Get-FileHash $source).Hash.ToLowerInvariant();configSha256=(Get-FileHash $config).Hash.ToLowerInvariant()})
   if(-not $passed){Write-Output $log;throw ('TLC_UNEXPECTED_RESULT_'+$model+'_'+$variant)}
  }finally{$p.Dispose()}
 }
}
$info=New-Object Diagnostics.ProcessStartInfo
$info.FileName=$java.Source;$info.Arguments='-version';$info.UseShellExecute=$false
$info.CreateNoWindow=$true;$info.RedirectStandardOutput=$true;$info.RedirectStandardError=$true
$vp=[Diagnostics.Process]::Start($info)
try{
 $vo=$vp.StandardOutput.ReadToEndAsync();$ve=$vp.StandardError.ReadToEndAsync()
 if(-not $vp.WaitForExit(10000)){$vp.Kill();throw 'JAVA_VERSION_DEADLINE'}
 $version=@(($vo.Result+$ve.Result) -split '\r?\n'|Where-Object {$_})
}finally{$vp.Dispose()}
$receipt=[ordered]@{schemaVersion='public.bounded-safety.v1';passed=$true;tool='TLC';toolRelease='v1.7.4';toolSha256=$expected;powerShell=$PSVersionTable.PSVersion.ToString();javaVersion=$version;sourceHead=$env:GITHUB_SHA;checks=@($checks.ToArray());scope='BOUNDED_ABSTRACT_NOT_CODE_REFINEMENT'}
$receipt|ConvertTo-Json -Depth 12|Set-Content (Join-Path $out 'receipt.json') -Encoding UTF8
$receipt|ConvertTo-Json -Depth 12
