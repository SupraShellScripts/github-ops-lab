# Repository topology discovery

## Purpose

This document defines a generic, implementation-independent contract for the **Discover** phase of repository-topology migration.

```text
Discover -> Plan -> Apply -> Verify
```

This public repository contains only reusable public-safe principles. It does not prescribe an operator's collector toolchain, estate topology, migration priorities, private relationships, credentials, or execution environment.

## Generic discovery contract

A normalized repository record may include repository identity, visibility, archived/fork/default-branch state, timestamps, public feature flags, workflow-dependency summaries, protection summaries, reference classifications, migration-risk flags, and provenance for every observed field.

Private access data, private repository relationships, operational priorities, credentials, and organization-specific authority semantics belong outside a public artifact unless deliberately published by their owner.

## Invariants

1. Discovery is read-only.
2. Raw observations remain distinct from normalized interpretation.
3. Every normalized field retains provenance or is explicitly unknown.
4. Missing data is not equivalent to `false` or `none`.
5. Public CI uses only public or synthetic inputs.
6. Public artifacts contain no unsanitized private discovery output.
7. Cross-repository references are classified before rewrite; historical provenance is not blindly changed.
8. Migration planning and mutation remain separate from discovery.
9. Verification must independently confirm the resulting topology.

## Public/private boundary

The durable public value here is the generic process and reusable validation semantics. Estate-specific collection orchestration, collector qualification, inventories, priorities, migration plans, private relationships, and raw evidence belong in an operator-controlled private plane.
