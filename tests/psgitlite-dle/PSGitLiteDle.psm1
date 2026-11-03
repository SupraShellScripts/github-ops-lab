# Public-original PSGitLite DLE engine, Windows PowerShell 5.1 / built-in .NET.
# No native Git executable, COM, Add-Type, external DLL, child process or network.
# Experimental isolated SHA-1 loose-object repository; not host deployment.
Set-StrictMode -Version Latest
$ErrorActionPreference='Stop'
Import-Module (Join-Path (Split-Path $PSScriptRoot -Parent) 'psgitlite-native/PSGitLiteCore.psm1') -Force
$script:utf8=[Text.UTF8Encoding]::new($false,$true)
$script:ascii=[Text.Encoding]::ASCII
$script:lf=[string][char]10

function Assert-DleId([string]$Id){
  if([string]::IsNullOrWhiteSpace($Id) -or $Id.Length -gt 64 -or
     $Id -cnotmatch '^[a-zA-Z0-9][a-zA-Z0-9_.-]*$' -or
     $Id.Contains('..') -or $Id.EndsWith('.') -or
     $Id.EndsWith('.lock',[StringComparison]::OrdinalIgnoreCase) -or
     $Id -match '^(?i:CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:[.]|$)'){throw 'DLE_INVALID_ID'}
}
function Assert-DleText([string]$Value,[int]$Max){
  if($null -eq $Value -or $Value.Length -gt $Max -or $Value.IndexOf([char]0) -ge 0){
    throw 'DLE_FIELD_BOUND'
  }
}
function Get-DleHex([byte[]]$Bytes){
  return ([BitConverter]::ToString($Bytes)).Replace('-','').ToLowerInvariant()
}
function Get-DleHash([byte[]]$Bytes){
  $h=[Security.Cryptography.SHA256]::Create()
  try{return Get-DleHex $h.ComputeHash($Bytes)}finally{$h.Dispose()}
}
function Get-DleRepo([string]$Path){
  $root=[IO.Path]::GetFullPath($Path)
  $git=[IO.Path]::Combine($root,'.git')
  $head=[IO.Path]::Combine($git,'HEAD')
  if(-not [IO.Directory]::Exists($git) -or -not [IO.File]::Exists($head) -or
      [IO.File]::ReadAllText($head).Trim() -cne 'ref: refs/heads/main'){
    throw 'DLE_REPO_UNSUPPORTED'
  }
  return [pscustomobject]@{Root=$root;Git=$git}
}
function Initialize-GitLiteDle{
  [CmdletBinding()]param([Parameter(Mandatory)][string]$RepositoryPath)
  $root=[IO.Path]::GetFullPath($RepositoryPath)
  $exists=[IO.Directory]::Exists([IO.Path]::Combine($root,'.git'))
  if(-not $exists){$null=New-GitLiteRepository -Path $root}
  $repo=Get-DleRepo $root
  return [pscustomobject]@{Repository=$repo.Root;Existing=$exists}
}
function Get-DleRef([object]$Repo,[string]$WorksetId){
  Assert-DleId $WorksetId
  return [IO.Path]::Combine($Repo.Git,'refs','airea51','dle',$WorksetId)
}
function Read-DleRef([string]$Path){
  if(-not [IO.File]::Exists($Path)){return $null}
  $id=[IO.File]::ReadAllText($Path).Trim()
  if($id -cnotmatch '^[0-9a-f]{40}$'){throw 'DLE_MALFORMED_REF'}
  return $id
}
function Read-DleObject([string]$Root,[string]$Id,[string]$Kind){
  $o=Get-GitLiteObject -RepositoryPath $Root -Sha $Id
  if($o.Type -cne $Kind){throw 'DLE_OBJECT_TYPE_MISMATCH'}
  return $o
}
function New-DleBlob([string]$Root,[string]$Text){
  $bytes=$script:utf8.GetBytes($Text)
  if($bytes.Length -gt 524288){throw 'DLE_BLOB_LIMIT'}
  $oid=New-GitLiteObject -RepositoryPath $Root -Type blob -Payload $bytes
  $null=Read-DleObject $Root $oid 'blob'
  return $oid
}
function New-DleTree([string]$Root,[string]$Baton,[string]$Checkpoint,[string]$Event){
  $files=@('baton.md','checkpoint.json','event.json')
  $texts=@($Baton,$Checkpoint,$Event)
  $stream=[IO.MemoryStream]::new()
  try{
    for($i=0;$i -lt $files.Count;$i++){
      $oid=New-DleBlob $Root $texts[$i]
      $name=$script:ascii.GetBytes('100644 '+$files[$i])
      $stream.Write($name,0,$name.Length);$stream.WriteByte(0)
      for($j=0;$j -lt 40;$j+=2){$stream.WriteByte([Convert]::ToByte($oid.Substring($j,2),16))}
    }
    $tree=New-GitLiteObject -RepositoryPath $Root -Type tree -Payload $stream.ToArray()
    $null=Read-DleObject $Root $tree 'tree'
    return $tree
  }finally{$stream.Dispose()}
}
function Read-DleTree([string]$Root,[string]$Id){
  $object=Read-DleObject $Root $Id 'tree'
  $bytes=$object.Data
  $names=@('baton.md','checkpoint.json','event.json')
  $result=@{}
  [int]$at=0
  foreach($name in $names){
    if($at -ge $bytes.Length){throw 'DLE_TREE_TRUNCATED'}
    $nul=[Array]::IndexOf($bytes,[byte]0,$at)
    if($nul -lt 0 -or $nul+21 -gt $bytes.Length){throw 'DLE_TREE_MALFORMED'}
    $entry=$script:ascii.GetString($bytes,$at,$nul-$at)
    if($entry -cne ('100644 '+$name)){throw 'DLE_TREE_UNEXPECTED_ENTRY'}
    $oidBytes=New-Object byte[] 20
    [Array]::Copy($bytes,$nul+1,$oidBytes,0,20)
    $blob=Read-DleObject $Root (Get-DleHex $oidBytes) 'blob'
    $result[$name]=$script:utf8.GetString($blob.Data)
    $at=$nul+21
  }
  if($at -ne $bytes.Length){throw 'DLE_TREE_EXTRA_ENTRY'}
  return $result
}
function Read-DleCommit([string]$Root,[string]$Id){
  $o=Read-DleObject $Root $Id 'commit'
  $text=$script:utf8.GetString($o.Data)
  $separation=$text.IndexOf($script:lf+$script:lf,[StringComparison]::Ordinal)
  if($separation -lt 0){throw 'DLE_COMMIT_MALFORMED'}
  $tree=$null;$parent=$null
  foreach($line in $text.Substring(0,$separation).Split([char]10)){
    if($line -cmatch '^tree ([0-9a-f]{40})$'){$tree=$Matches[1]}
    elseif($line -cmatch '^parent ([0-9a-f]{40})$'){
      if($parent){throw 'DLE_MERGE_COMMIT_UNSUPPORTED'}
      $parent=$Matches[1]
    }
  }
  if(!$tree){throw 'DLE_TREE_NOT_FOUND'}
  $items=Read-DleTree $Root $tree
  $event=$items['event.json']|ConvertFrom-Json
  $checkpoint=$items['checkpoint.json']|ConvertFrom-Json
  if($event.schemaVersion -cne 'airea51.dle-event.v1' -or
     $checkpoint.schemaVersion -cne 'airea51.dle-checkpoint.v1' -or
     $event.parentCommit -cne $parent -or $checkpoint.previousCommit -cne $parent -or
     $event.requestId -cne $checkpoint.requestId -or
     $event.worksetId -cne $checkpoint.worksetId -or
     $event.requestDigest -cne $checkpoint.requestDigest -or
     $event.status -cne $checkpoint.status -or
     $event.nextBaton -cne $items['baton.md']){
    throw 'DLE_INCONSISTENT_CHECKPOINT'
  }
  return [pscustomobject]@{Head=$Id;Parent=$parent;Tree=$tree;Event=$event;Checkpoint=$checkpoint;Baton=$items['baton.md']}
}
function Get-GitLiteDleSnapshot {
  [CmdletBinding()]param([Parameter(Mandatory)][string]$RepositoryPath,
    [Parameter(Mandatory)][string]$WorksetId)
  $repo=Get-DleRepo $RepositoryPath
  $head=Read-DleRef (Get-DleRef $repo $WorksetId)
  if(!$head){return [pscustomobject]@{WorksetId=$WorksetId;Head=$null;Status='EMPTY';Recovery='CREATE_CHECKPOINT'}}
  $record=Read-DleCommit $repo.Root $head
  if($record.Event.worksetId -cne $WorksetId){throw 'DLE_WRONG_WORKSET'}
  $recovery=if($record.Event.status -in @('INTENT','OBSERVED','UNKNOWN')){'RECONCILE_REQUIRED'}
            elseif($record.Event.status -ceq 'FAILED'){'DIAGNOSE_FIRST_FAILURE'}
            else{'CONTINUE_FROM_BATON'}
  return [pscustomobject]@{WorksetId=$WorksetId;Head=$head;Parent=$record.Parent;
    Status=$record.Event.status;Recovery=$recovery;NextBaton=$record.Baton;Event=$record.Event}
}
function Get-GitLiteDleHistory {
  [CmdletBinding()]param([Parameter(Mandatory)][string]$RepositoryPath,
    [Parameter(Mandatory)][string]$WorksetId,[ValidateRange(1,128)][int]$MaxCount=32)
  $repo=Get-DleRepo $RepositoryPath
  $head=Read-DleRef (Get-DleRef $repo $WorksetId)
  $seen=[Collections.Generic.HashSet[string]]::new([StringComparer]::Ordinal)
  for($i=0;$i -lt $MaxCount -and $head;$i++){
    if(!$seen.Add($head)){throw 'DLE_COMMIT_CYCLE'}
    $r=Read-DleCommit $repo.Root $head
    if($r.Event.worksetId -cne $WorksetId){throw 'DLE_WRONG_WORKSET'}
    [pscustomobject]@{Head=$r.Head;Parent=$r.Parent;Event=$r.Event}
    $head=$r.Parent
  }
}
function New-GitLiteDleCheckpoint {
  [CmdletBinding()]param([Parameter(Mandatory)][string]$RepositoryPath,
    [Parameter(Mandatory)][string]$WorksetId,
    [Parameter(Mandatory)][string]$RequestId,
    [Parameter(Mandatory)][string]$StepId,
    [Parameter(Mandatory)][ValidateSet('Discover','Observe','Plan','Apply','Verify','Reconcile')][string]$Phase,
    [Parameter(Mandatory)][ValidateSet('INTENT','OBSERVED','VERIFIED','FAILED','UNKNOWN')][string]$Status,
    [Parameter(Mandatory)][string]$Message,
    [Parameter(Mandatory)][string]$NextBaton,
    [AllowEmptyString()][string]$ExpectedHead='',
    [string]$IntendedEffect='',
    [string]$ObservedEffect='',
    [string]$Actor='synthetic-agent',
    [string[]]$EvidenceRefs=@()
  )
  Assert-DleId $WorksetId;Assert-DleId $RequestId;Assert-DleId $StepId
  Assert-DleText $Message 4096;Assert-DleText $NextBaton 8192
  Assert-DleText $IntendedEffect 4096;Assert-DleText $ObservedEffect 4096
  Assert-DleText $Actor 128
  if($Actor -cnotmatch '^[a-zA-Z0-9_.-]+$'){throw 'DLE_INVALID_ACTOR'}
  if($EvidenceRefs.Count -gt 16){throw 'DLE_EVIDENCE_LIMIT'}
  foreach($e in $EvidenceRefs){Assert-DleText $e 256}
  if($ExpectedHead -and $ExpectedHead -cnotmatch '^[0-9a-f]{40}$'){throw 'DLE_INVALID_EXPECTED_HEAD'}
  $request=[ordered]@{worksetId=$WorksetId;requestId=$RequestId;stepId=$StepId;
    phase=$Phase;status=$Status;message=$Message;nextBaton=$NextBaton;
    intendedEffect=$IntendedEffect;observedEffect=$ObservedEffect;actor=$Actor;
    evidenceRefs=@($EvidenceRefs)}
  $requestJson=ConvertTo-Json -InputObject $request -Depth 5 -Compress
  $digest=Get-DleHash $script:utf8.GetBytes($requestJson)
  $repo=Get-DleRepo $RepositoryPath
  $ref=Get-DleRef $repo $WorksetId
  $parent=Read-DleRef $ref
  if($parent){$null=Read-DleCommit $repo.Root $parent}
  if(($parent -ne $ExpectedHead) -and (-not (!$parent -and !$ExpectedHead))){
    if($parent){
      $old=Read-DleCommit $repo.Root $parent
      if($old.Event.requestId -ceq $RequestId -and $old.Event.requestDigest -ceq $digest){
        return [pscustomobject]@{Head=$parent;Parent=$old.Parent;Replay=$true;Status=$old.Event.status}
      }
    }
    throw 'DLE_STALE_HEAD'
  }
  $seen=[Collections.Generic.HashSet[string]]::new([StringComparer]::Ordinal)
  $cursor=$parent
  for($i=0;$i -lt 128 -and $cursor;$i++){
    if(!$seen.Add($cursor)){throw 'DLE_COMMIT_CYCLE'}
    $old=Read-DleCommit $repo.Root $cursor
    if($old.Event.worksetId -cne $WorksetId){throw 'DLE_WRONG_WORKSET'}
    if($old.Event.requestId -ceq $RequestId){throw 'DLE_REQUEST_REPLAY'}
    $cursor=$old.Parent
  }
  if($cursor){throw 'DLE_HISTORY_BOUND'}
  $now=[DateTimeOffset]::UtcNow
  $event=[ordered]@{schemaVersion='airea51.dle-event.v1';worksetId=$WorksetId;
    requestId=$RequestId;requestDigest=$digest;stepId=$StepId;phase=$Phase;status=$Status;
    message=$Message;nextBaton=$NextBaton;intendedEffect=$IntendedEffect;
    observedEffect=$ObservedEffect;actor=$Actor;evidenceRefs=@($EvidenceRefs);
    createdUtc=$now.ToString('yyyy-MM-ddTHH:mm:ss.fffZ',[Globalization.CultureInfo]::InvariantCulture);
    parentCommit=$parent}
  $checkpoint=[ordered]@{schemaVersion='airea51.dle-checkpoint.v1';worksetId=$WorksetId;
    requestId=$RequestId;status=$Status;stepId=$StepId;phase=$Phase;
    previousCommit=$parent;requestDigest=$digest}
  $eventJson=(ConvertTo-Json -InputObject $event -Depth 5 -Compress)+$script:lf
  $checkpointJson=(ConvertTo-Json -InputObject $checkpoint -Depth 5 -Compress)+$script:lf
  $tree=New-DleTree $repo.Root $NextBaton $checkpointJson $eventJson
  $identity='AIrea51 DLE <airea51-dle@example.invalid> '+$now.ToUnixTimeSeconds()+' +0000'
  $parents=if($parent){'parent '+$parent+$script:lf}else{''}
  $body='tree '+$tree+$script:lf+$parents+'author '+$identity+$script:lf+
    'committer '+$identity+$script:lf+$script:lf+'DLE checkpoint: '+$WorksetId+' '+$RequestId+$script:lf
  $commit=New-GitLiteObject -RepositoryPath $repo.Root -Type commit -Payload ($script:utf8.GetBytes($body))
  $validated=Read-DleCommit $repo.Root $commit
  if($validated.Event.requestDigest -cne $digest){throw 'DLE_PRECOMMIT_INTEGRITY'}
  $directory=[IO.Path]::GetDirectoryName($ref)
  [void][IO.Directory]::CreateDirectory($directory)
  $lock=$ref+'.lock'
  $stream=[IO.FileStream]::new($lock,[IO.FileMode]::CreateNew,[IO.FileAccess]::Write,[IO.FileShare]::None)
  try{
    $actual=Read-DleRef $ref
    if(($actual -ne $parent) -and (-not (!$actual -and !$parent))){throw 'DLE_STALE_HEAD'}
    $newBytes=$script:ascii.GetBytes($commit+$script:lf)
    $stream.Write($newBytes,0,$newBytes.Length)
    $stream.Flush($true)
    $stream.Dispose();$stream=$null
    if([IO.File]::Exists($ref)){
      $backup=$ref+'.backup-'+[guid]::NewGuid().ToString('N')
      [IO.File]::Replace($lock,$ref,$backup)
      if([IO.File]::Exists($backup)){[IO.File]::Delete($backup)}
    }else{[IO.File]::Move($lock,$ref)}
  }finally{
    if($null -ne $stream){$stream.Dispose()}
    if([IO.File]::Exists($lock)){[IO.File]::Delete($lock)}
  }
  $recheck=Get-GitLiteDleSnapshot -RepositoryPath $repo.Root -WorksetId $WorksetId
  if($recheck.Head -cne $commit){throw 'DLE_POSTCOMMIT_INTEGRITY'}
  return [pscustomobject]@{Head=$commit;Parent=$parent;Replay=$false;Status=$Status;RequestDigest=$digest}
}
Export-ModuleMember -Function Initialize-GitLiteDle,New-GitLiteDleCheckpoint,Get-GitLiteDleSnapshot,Get-GitLiteDleHistory
