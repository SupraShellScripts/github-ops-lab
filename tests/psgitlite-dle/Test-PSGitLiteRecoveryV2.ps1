#requires -Version 5.1
# Native synthetic v2 state machine test. No source secrets or Git executable.
Set-StrictMode -Version Latest
$ErrorActionPreference='Stop'
Import-Module (Join-Path $PSScriptRoot 'PSGitLiteRecoveryV2.psm1') -Force
function Assert([bool]$Ok,[string]$Message){
  if(!$Ok){throw ('FAIL '+$Message)}
  Write-Output ('PASS '+$Message)
}
function E([string]$Request,[string]$Kind,[string]$Status,
           [string]$Effect='',[string]$Phase='Observe',
           [string[]]$Evidence=@(),[string]$Workset='unit'){
  return [pscustomobject]@{
    schemaVersion='airea51.dle-event.v2';worksetId=$Workset;
    requestId=$Request;eventKind=$Kind;effectId=$Effect;
    status=$Status;phase=$Phase;evidenceRefs=@($Evidence)}
}
function Decide([string]$Name,[object[]]$History,[string]$Expected){
  $assessment=Get-PSGitLiteRecoveryDecision -Events $History
  Assert ($assessment.Verdict -ceq $Expected -and !$assessment.AutoReexecuteAllowed) $Name
}
function Refuse([string]$Name,[object[]]$History){
  $denied=$false
  try{$null=Get-PSGitLiteRecoveryDecision -Events $History}catch{$denied=$true}
  Assert $denied $Name
}
$a=E r1 EXTERNAL_EFFECT INTENT effect-A Apply
$b=E r2 EXTERNAL_EFFECT INTENT effect-B Apply
$va=E r3 EXTERNAL_EFFECT VERIFIED effect-A Verify @('fixture:A')
$vb=E r4 EXTERNAL_EFFECT VERIFIED effect-B Verify @('fixture:B')
$passive=E r5 PASSIVE_OBSERVATION OBSERVED
$failure=E r6 EXTERNAL_EFFECT FAILED effect-A Apply
$recover=E r7 EXTERNAL_EFFECT VERIFIED effect-A Reconcile @('fixture:operator-reviewed')
Decide 'unresolved intent refuses continuation' @($a) RECONCILE_REQUIRED
Decide 'passive later observation does not clear A' @($a,$passive) RECONCILE_REQUIRED
Decide 'unrelated B verified cannot clear A' @($a,$b,$vb) RECONCILE_REQUIRED
Decide 'both effects verified by own evidence allow continuation' @($a,$b,$va,$vb) CONTINUE_FROM_BATON
Decide 'standalone passive observation has no effect' @($passive) CONTINUE_FROM_BATON
Decide 'failed A dominates later verified B' @($a,$failure,$b,$vb) DIAGNOSE_FIRST_FAILURE
Decide 'Reconcile with evidence resolves failed A' @($a,$failure,$recover) CONTINUE_FROM_BATON
$old=[pscustomobject]@{schemaVersion='airea51.dle-event.v1';requestId='old1';status='INTENT';phase='Apply'}
Decide 'uncorrelated legacy intent refuses continuation' @($old,$passive) RECONCILE_REQUIRED
$oldFail=[pscustomobject]@{schemaVersion='airea51.dle-event.v1';requestId='old2';status='FAILED';phase='Apply'}
Decide 'legacy FAILED still dominates B' @($oldFail,$b,$vb) DIAGNOSE_FIRST_FAILURE
Refuse 'cannot verify effect without prior intent' @($va)
Refuse 'verified effect without evidence refused' @($a,(E r8 EXTERNAL_EFFECT VERIFIED effect-A Verify))
Refuse 'null evidence is not evidence' @($a,([pscustomobject]@{schemaVersion='airea51.dle-event.v2';worksetId='unit';requestId='r9';eventKind='EXTERNAL_EFFECT';effectId='effect-A';status='VERIFIED';phase='Verify';evidenceRefs=$null}))
Refuse 'blank evidence refused' @($a,(E r10 EXTERNAL_EFFECT VERIFIED effect-A Verify @('')))
Refuse 'FAILED requires Reconcile, not Verify' @($a,$failure,(E r11 EXTERNAL_EFFECT VERIFIED effect-A Verify @('fixture:x')))
Refuse 'non-effect cannot declare INTENT' @((E r12 PASSIVE_OBSERVATION INTENT))
Refuse 'duplicate request ID refused' @($a,$a)
Refuse 'duplicate effect INTENT refused' @($a,(E r13 EXTERNAL_EFFECT INTENT effect-A Apply))
Refuse 'terminal effect cannot reopen' @($a,$va,(E r14 EXTERNAL_EFFECT UNKNOWN effect-A Apply))
Refuse 'cross-workset event refused' @($a,(E r15 PASSIVE_OBSERVATION OBSERVED '' Observe @() other))
Refuse 'out-of-phase external intent refused' @((E r16 EXTERNAL_EFFECT INTENT effect-A Plan))
Refuse 'invalid event kind refused' @((E r17 UNKNOWN_KIND OBSERVED))
Refuse 'non-effect UNKNOWN status refused' @((E r18 CHECKPOINT UNKNOWN))
$many=@()
for($i=0;$i -lt 129;$i++){
  $many+=@(E ('req'+$i) PASSIVE_OBSERVATION OBSERVED)
}
Refuse 'more than 128 events requires bounded migration' $many
Write-Output 'PSGITLITE_RECOVERY_V2_NATIVE_PASS'
