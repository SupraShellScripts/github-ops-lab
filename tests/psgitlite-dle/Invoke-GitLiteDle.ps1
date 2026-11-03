param(
  [Parameter(Mandatory)][ValidateSet('Init','Inspect','History','Checkpoint')][string]$Command,
  [Parameter(Mandatory)][string]$RepositoryPath,
  [string]$WorksetId,
  [string]$RequestId,
  [string]$StepId,
  [ValidateSet('Discover','Observe','Plan','Apply','Verify','Reconcile')][string]$Phase='Observe',
  [ValidateSet('INTENT','OBSERVED','VERIFIED','FAILED','UNKNOWN')][string]$Status='OBSERVED',
  [string]$Message='',
  [string]$NextBaton='',
  [AllowEmptyString()][string]$ExpectedHead='',
  [string]$IntendedEffect='',
  [string]$ObservedEffect='',
  [string]$Actor='synthetic-agent',
  [string]$ApprovalRef='',
  [string]$SourceRootDigest='',
  [string[]]$EvidenceRefs=@(),
  [ValidateSet('Human','Json','Jsonl')][string]$OutputFormat='Json'
)
# Command facade for human, automation and agents. No executable beyond PowerShell.
Set-StrictMode -Version Latest
$ErrorActionPreference='Stop'
Import-Module (Join-Path $PSScriptRoot 'PSGitLiteDle.psm1') -Force
try {
  switch($Command) {
    Init { $result=Initialize-GitLiteDle -RepositoryPath $RepositoryPath }
    Inspect {
      if(!$WorksetId){throw 'DLE_WORKSET_REQUIRED'}
      $result=Get-GitLiteDleSnapshot -RepositoryPath $RepositoryPath -WorksetId $WorksetId
    }
    History {
      if(!$WorksetId){throw 'DLE_WORKSET_REQUIRED'}
      $result=@(Get-GitLiteDleHistory -RepositoryPath $RepositoryPath -WorksetId $WorksetId)
    }
    Checkpoint {
      if(!$WorksetId -or !$RequestId -or !$StepId -or !$Message -or !$NextBaton){
        throw 'DLE_CHECKPOINT_FIELDS_REQUIRED'
      }
      $result=New-GitLiteDleCheckpoint -RepositoryPath $RepositoryPath -WorksetId $WorksetId -RequestId $RequestId -StepId $StepId -Phase $Phase -Status $Status -Message $Message -NextBaton $NextBaton -ExpectedHead $ExpectedHead -IntendedEffect $IntendedEffect -ObservedEffect $ObservedEffect -Actor $Actor -EvidenceRefs $EvidenceRefs -ApprovalRef $ApprovalRef -SourceRootDigest $SourceRootDigest
    }
  }
  if($OutputFormat -eq 'Json'){
    Write-Output (ConvertTo-Json -InputObject $result -Depth 10 -Compress)
  }elseif($OutputFormat -eq 'Jsonl'){
    foreach($item in @($result)){Write-Output (ConvertTo-Json -InputObject $item -Depth 10 -Compress)}
  }else{
    foreach($item in @($result)){
      if($Command -eq 'History'){
        Write-Output ('DLE head='+$item.Head+' status='+$item.Event.status+' step='+$item.Event.stepId)
      }elseif($Command -eq 'Inspect'){
        Write-Output ('DLE workset='+$item.WorksetId+' head='+$item.Head+' status='+$item.Status+' recovery='+$item.Recovery)
        if($item.NextBaton){Write-Output ('Next baton: '+$item.NextBaton)}
      }elseif($Command -eq 'Checkpoint'){
        Write-Output ('DLE checkpoint='+$item.Head+' replay='+$item.Replay+' status='+$item.Status)
      }else{Write-Output ('DLE repository='+$item.Repository+' existing='+$item.Existing)}
    }
  }
}catch{
  # Deliberately stable no-stack failure projection; no source/event payload echo.
  Write-Error ('DLE_OPERATION_FAILED: '+$_.Exception.Message) -ErrorAction Continue
  exit 2
}
