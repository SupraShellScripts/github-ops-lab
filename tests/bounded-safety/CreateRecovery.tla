-------------------------- MODULE CreateRecovery --------------------------
EXTENDS Naturals
CONSTANT Unsafe
VARIABLES source, test, journal, altered, erasedAltered, registry, admitted
vars == <<source, test, journal, altered, erasedAltered, registry, admitted>>
Init == /\ source = FALSE /\ test = FALSE /\ journal = "new"
        /\ altered = FALSE /\ erasedAltered = FALSE
        /\ registry = 0 /\ admitted = FALSE
CreateSource == /\ journal = "new" /\ ~source
                /\ source' = TRUE /\ journal' = "source"
                /\ UNCHANGED <<test, altered, erasedAltered, registry, admitted>>
CreateTest == /\ journal = "source" /\ ~test
              /\ test' = TRUE /\ journal' = "tested"
              /\ UNCHANGED <<source, altered, erasedAltered, registry, admitted>>
Alter == /\ source /\ ~altered /\ altered' = TRUE
         /\ UNCHANGED <<source, test, journal, erasedAltered, registry, admitted>>
DriftRegistry == /\ registry' = 1 - registry
                 /\ UNCHANGED <<source, test, journal, altered, erasedAltered, admitted>>
Promote == /\ journal = "tested" /\ source /\ test /\ ~admitted
           /\ (Unsafe \/ (~altered /\ registry = 0))
           /\ admitted' = TRUE /\ journal' = "promoted"
           /\ erasedAltered' = erasedAltered \/ altered \/ registry # 0
           /\ UNCHANGED <<source, test, altered, registry>>
Recover == /\ journal \in {"source","tested"} /\ (Unsafe \/ ~altered)
           /\ source' = FALSE /\ test' = FALSE /\ journal' = "rolledback"
           /\ erasedAltered' = erasedAltered \/ altered
           /\ UNCHANGED <<altered, registry, admitted>>
Next == CreateSource \/ CreateTest \/ Alter \/ DriftRegistry \/ Promote \/ Recover
Spec == Init /\ [][Next]_vars
TypeOK == /\ source \in BOOLEAN /\ test \in BOOLEAN /\ altered \in BOOLEAN
          /\ erasedAltered \in BOOLEAN /\ registry \in {0,1}
          /\ admitted \in BOOLEAN
          /\ journal \in {"new","source","tested","promoted","rolledback"}
Safety == ~erasedAltered /\ (admitted => (source /\ test))
=============================================================================
