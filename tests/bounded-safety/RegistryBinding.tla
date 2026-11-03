------------------------- MODULE RegistryBinding -------------------------
EXTENDS Naturals, Integers
CONSTANT Unsafe
VARIABLES registry, grant, consumed, executions, bindingViolation
vars == <<registry, grant, consumed, executions, bindingViolation>>
Init == /\ registry = 0 /\ grant = -1 /\ consumed = FALSE
        /\ executions = 0 /\ bindingViolation = FALSE
Approve == /\ grant = -1 /\ grant' = registry
           /\ UNCHANGED <<registry, consumed, executions, bindingViolation>>
Rotate == /\ registry' = 1 - registry
          /\ UNCHANGED <<grant, consumed, executions, bindingViolation>>
Execute == /\ grant # -1 /\ executions < 2
           /\ (Unsafe \/ (~consumed /\ registry = grant))
           /\ executions' = executions + 1 /\ consumed' = TRUE
           /\ bindingViolation' = bindingViolation \/ registry # grant
           /\ UNCHANGED <<registry, grant>>
Next == Approve \/ Rotate \/ Execute
Spec == Init /\ [][Next]_vars
TypeOK == /\ registry \in {0,1} /\ grant \in {-1,0,1}
          /\ consumed \in BOOLEAN /\ executions \in 0..2
          /\ bindingViolation \in BOOLEAN
Safety == ~bindingViolation /\ executions <= 1
=============================================================================
