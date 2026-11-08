# P4 Transition Implementation Baseline

> **SUPERSEDED:** Historical P4 v1.0 record. Use `../../README_v1.1.md`.

**Status:** CONTROLLED P4 READING INDEX
**Frozen product baseline:** `docs/frozen/v2.1/`
**Transition baseline:** `docs/transition/`

This directory contains the implementation baseline for the narrowed P4 IA
Runtime Foundation. It does not amend any document under
`docs/frozen/v2.1/`.

## Required Reading Order

1. `docs/frozen/v2.1/README_FROZEN_BASELINE.md`
2. Frozen Priority-A documents and machine-readable contracts
3. Frozen Agent-to-NSL Integration Contract
4. Frozen Result Publication boundary
5. `docs/transition/00` through `docs/transition/05`
6. `P4_Agent_Runtime_Foundation_SRS_v1.0.md`
7. `P4_Result_Persistence_and_Publication_Design_Hardening_FROZEN_v1.0.md`
8. `P4_IA_Runtime_Foundation_Scope_Review_v1.0.md`
9. `P4_Issue_Register_v1.0.md`
10. `P4_Result_Persistence_Publication_Traceability_v1.0.md`
11. Current branch source code
12. `P4_Source_Audit_and_Implementation_Plan_v1.0.md`

## Authority Rule

```text
Frozen semantic authority
> P4 SRS
> P4 Design Hardening Frozen decisions for SRS gaps
> P4 IA Runtime Foundation scope review
> P4 Issue Register and traceability records
> implementation convenience
```

The scope review narrows the current implementation wave where Project and
publication authority are unavailable. It does not silently reinterpret a
higher contract. Any deferred Frozen obligation remains recorded as deferred
and cannot be reported as passing P4 evidence.

## Change Rule

- Do not modify `docs/frozen/v2.1/`.
- Preserve v1.0 public Chat/RAG behavior and UI.
- Keep Conversation project-neutral.
- Treat IA as a persistent personal identity: login creates no IA, and the
  first authenticated prompt resolves/provisions it idempotently.
- Use opaque PERSONAL scope for unresolved/personal work; never disguise it as
  a default Project.
- Preserve Conversation turns in a new append-only owner-private journal while
  retaining `ae_chat_interactions` as the v1.0 compatibility projection.
- Treat Conversation Weekly Digest as a bounded skeleton, not canonical Agent
  Memory; production LLM composition and retrieval use remain deferred.
- Do not add `project_id`, Project Agent, Enterprise OS, `MOCK_ENTERPRISE_OS`,
  or WC to P4 source or migrations.
- Use `IAChatRun`, not AgentExecution, for the project-neutral transition row.
- Do not implement canonical AgentResult/ResultDelivery or fake publication
  preflight/ACK evidence in P4.
- Implement only the Slices in the reviewed narrowed plan.

## STEP 9 Outcome

STEP 9 now defines a nine-Slice IA Runtime Foundation:

- refactor the existing Chat/RAG application boundary first;
- lazily resolve one persistent server-managed personal IA and PERSONAL scope
  on the first authenticated prompt, never on login;
- change Workspace 1:1 ChatDocument into Workspace 1:N Conversation while
  preserving the existing public `chat_document_id` compatibility value;
- persist ordered complete turns through an append-only owner-private
  message/event journal while preserving the mutable compatibility projection;
- add an immutable ISO-week Conversation Weekly Digest skeleton using mock
  composition and existing maintenance-job boundaries;
- admit project-neutral IAChatRun records idempotently;
- provide durable job/attempt/lease/restart behavior;
- execute the existing synchronous or asynchronous Chat/RAG path exactly once;
- close with real PostgreSQL smoke, full regression/coverage, unchanged
  Playwright Chat/RAG acceptance, Frozen checksum, and excluded-scope checks.

Project discovery, clarification, Enterprise OS resolution, PA, WC delegation,
canonical ExecutionTrigger/AgentExecution, and canonical AgentResult/
ResultDelivery remain later work. Canonical Project-partitioned Agent Memory,
production LLM digest composition, scheduling, and retrieval injection also
remain later work. STEP 8.1 preserves the result/publication design for that
later phase.

The STEP 9 documents are a review baseline, not implementation evidence.
Implementation begins only after this corrected boundary is accepted.
