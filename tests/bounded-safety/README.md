# Public-original bounded safety fixtures

These newly authored abstract fixtures contain no product source, credentials,
private links, local paths or operational evidence. They model generic one-use
registry-bound authorization and create/recovery/promotion ordering.

Official TLC checks TypeOK and Safety in each finite model. Safe configurations
must exit zero. Deliberately Unsafe configurations must fail specifically with
an invariant Safety counterexample; parser/download/timeouts do not count.
The bounds are two registry identities, one grant, at most two executions and
a single source/test transaction. No liveness, power-loss durability, OS isolation,
code refinement, cryptographic authentication or actual deployment is proved.

Workflow uses standard public Ubuntu and Windows runners, official pinned TLC
release bytes, bounded deadlines and logs with exact model/config/tool hashes.
No product repository checkout or secrets are required.
