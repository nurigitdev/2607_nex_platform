# P4 Agent Runtime Foundation Issue Register v1.0

**Status:** ACTIVE TRANSITION REGISTER
**Opened:** 2026-10-12
**Scope:** narrowed project-neutral P4 IA Runtime Foundation

Severity meanings:

- `P0`: unsafe to continue;
- `P1`: must be decided before affected implementation;
- `P2`: must be closed before P4 Foundation acceptance;
- `P3`: documentation or low-risk follow-up.

| ID | Severity | Source | Issue | Controlling decision | Status / next action |
|---|---:|---|---|---|---|
| P4-ISSUE-001 | P1 | P4 SRS constraint 03 | No standalone machine-readable AgentExecution schema was found. | P4 does not implement or claim canonical AgentExecution. Use `IAChatRun` as a clearly named transition aggregate. Preserve Frozen state/phase vocabulary for the later canonical phase. | `DEFERRED_CANONICAL_RUNTIME`; no P4 Slice may close this by inventing a schema. |
| P4-ISSUE-002 | P1 | P4 SRS constraint 02 | Trusted ACTIVE IA provisioning/resolution was not fixed. | Add one persistent server-managed IAIdentity and one ACTIVE assignment per `(tenant_id, principal_ref)`. Resolve it per interaction; do not bind a Conversation permanently or trust browser identity. | `SOURCE_RESOLVED`; P4-S2/P4-S5. |
| P4-ISSUE-003 | P1 | P4 SRS constraint 01; Frozen Intent design | PROMPT ExecutionTrigger requires `project_id`, but IA intent may begin before a Project is known. | No fake/default Project, no Workspace/Conversation substitution, and no Enterprise OS mock. P4 uses project-neutral IAChatRun and defers canonical PROMPT admission until Project-resolution semantics are approved. | `SCOPE_DEFERRED`; P4-S5 must prove honest naming and absence of Project authority. |
| P4-ISSUE-004 | P1 | P4 SRS constraint 05 | Conformant publication ACK requires current authorization, Project scope, classification, and visibility evidence. | Preserve STEP 8.1 design; do not implement or fake canonical ResultDelivery in the narrowed P4. Existing Chat/RAG response persistence remains authoritative. | `DEFERRED_RESULT_PUBLICATION`. |
| P4-ISSUE-005 | P1 | STEP 7 review | Frozen SQL projection alone cannot reconstruct every required AgentResult schema field. | Retain the STEP 8.1 `result_envelope_json` decision for the later canonical result phase. | `DESIGN_RESOLVED_IMPLEMENTATION_DEFERRED`. |
| P4-ISSUE-006 | P1 | STEP 7/8 review | Canonical result, delivery plan, and publication job require atomic persistence. | Retain the STEP 8.1 atomicity decision; add no partial P4 implementation. | `DESIGN_RESOLVED_IMPLEMENTATION_DEFERRED`. |
| P4-ISSUE-007 | P1 | STEP 7 helper probe | Empty delivery collections can incorrectly appear complete. | Retain the non-empty required-plan guard for the later publication phase. | `DESIGN_RESOLVED_IMPLEMENTATION_DEFERRED`. |
| P4-ISSUE-008 | P1 | P4-RES-010 | Frozen assets require `result_hash` but do not completely fix its algorithm. | Retain STEP 8.1 canonical JSON/SHA-256 decision; P4 does not create AgentResult. | `DESIGN_RESOLVED_IMPLEMENTATION_DEFERRED`. |
| P4-ISSUE-009 | P3 | P4 SRS line 334 | Rollout mode refers to Section 22, but rollout is Section 23. | Treat the reference as Section 23 without changing the SRS. | `DOCUMENTED`. |
| P4-ISSUE-010 | P3 | Transition baseline record | Historical record says the Platform `v1.0` tag was absent. | Preserve the historical record and use the independent `00A` tag-verification addendum. | `CLOSED`. |
| P4-ISSUE-011 | P2 | STEP 7 SQL review | Publication reconciliation outcome has no explicit append-only SQL store. | External-target reconciliation remains deferred to P9. | `DEFERRED_P9`. |
| P4-ISSUE-012 | P2 | STEP 7 helper probe | Background lineage helper accepts claim generation zero while schema/SQL require at least one. | P4 runs IA Chat only; correct this before CA/PA/EA execution. | `DEFERRED_P6`. |
| P4-ISSUE-013 | P1 | OA source audit | OA has no current Project/classification/resource-visibility decision required by canonical publication. | No P4 workaround. Revisit with authoritative Project resolution and result publication. | `DEFERRED_AUTHORITY_INTEGRATION`. |
| P4-ISSUE-014 | P1 | AE async source audit | Async CX generation can terminalize after initial admission, so a single inline wrapper may strand a run or replay generation. | Persist a waiting compatibility step and admit a deduplicated CONTINUE job from authoritative refresh/cancel/recovery terminalization. | `SOURCE_RESOLVED`; P4-S7. |
| P4-ISSUE-015 | P2 | Shared job source audit | Existing `service_jobs` does not own the IA runtime run/attempt/lease lifecycle. | Add dedicated IA runtime job and attempt tables. Reuse proven queue algorithms but make no Frozen RuntimeJob conformance claim. | `SOURCE_RESOLVED`; P4-S6. |
| P4-ISSUE-016 | P1 | AE workspace source audit | One unique `chat_document_id` on `ae_workspaces` prevents Workspace 1:N Conversation. | Add first-class project-neutral Conversation rows and retain the old field only as a default compatibility pointer. | `SOURCE_RESOLVED`; P4-S3. |
| P4-ISSUE-017 | P1 | Initial STEP 9 scope review | The first review introduced a dev/test `MOCK_ENTERPRISE_OS` despite Enterprise OS being outside P4. | Remove the emulator, Project Authority port, Project configuration, and all related tests from P4. | `SCOPE_CORRECTED`; excluded-scope scan at P4-S9. |
| P4-ISSUE-018 | P1 | AE Chat persistence audit | Full user prompts cannot be restored from hash/preview alone, while the current interaction row is mutable. | Add an append-only ordered message/event journal with owner-private full content; retain the interaction row as a compatibility projection and keep raw content out of runtime metadata. | `SOURCE_RESOLVED`; P4-S3. |
| P4-ISSUE-019 | P1 | Frozen Intent Resolution review | Binding one Conversation to one Project contradicts interaction-level Project discovery and clarification. | Conversation has no Project column or binding. Future resolved Project scope belongs to an interaction/execution/delegation contract. | `SOURCE_RESOLVED`; P4-S3 and P4-S9 exclusion checks. |
| P4-ISSUE-020 | P1 | STEP 9 scope correction | A transition row could be mistaken for Frozen AgentExecution conformance. | Use `IAChatRun`/`ia_chat_run_id`, document the limitation in APIs/reports, and prohibit `AgentExecution` success claims in P4. | `SOURCE_RESOLVED`; P4-S5/P4-S9. |
| P4-ISSUE-021 | P1 | Frozen Memory design; AE Chat source audit | The required append-only interaction history cannot be provided by mutable `ae_chat_interactions`. | Keep that table as the v1.0 projection and add immutable Conversation message/event records. Corrections append superseding records; ordinary update/delete APIs are prohibited for the journal. | `SOURCE_RESOLVED`; P4-S3. |
| P4-ISSUE-022 | P1 | P4 scope review | Personal or unresolved interactions need stable ownership, but a default Project would make AE an unauthorized Project authority. | Add opaque PERSONAL scope per tenant/principal/IA. It is not `project_id` and cannot create PA or WC delegation. | `SOURCE_RESOLVED`; P4-S2. |
| P4-ISSUE-023 | P1 | Frozen Agent Memory review | Canonical Agent Work Memory requires work classification and Project-partitioned weekly summaries that P4 cannot resolve. | Add only a Conversation Weekly Digest skeleton with immutable OPEN/FINAL/ADDENDUM versions and source hashes. Defer canonical Agent Memory, production LLM composition, scheduling, and retrieval injection. | `SCOPE_BOUNDED`; P4-S4/P4-S9. |
| P4-ISSUE-024 | P1 | IA lifecycle review | Creating a new IA at every login or prompt would break persistent identity and lineage. | Login changes only the OA session. Lazily provision one persistent IA/assignment/PERSONAL scope on the first authenticated prompt, with concurrency-safe winner/reload behavior; every prompt creates a run/job, not an IA. | `SOURCE_RESOLVED`; P4-S2. |

## Frozen Vocabulary Reference

The Frozen AgentExecution vocabulary remains a future canonical-runtime
reference and is not assigned to IAChatRun.

States:

```text
QUEUED
RUNNING
WAITING_INPUT
WAITING_CONFIRMATION
WAITING_APPROVAL
WAITING_DEPENDENCY
RECONCILIATION_REQUIRED
SUCCEEDED
FAILED
BLOCKED
ESCALATED
CANCELLED
```

Phases:

```text
INTAKE
BASE_CONTEXT
INTENT_RESOLUTION
CONTEXT_EXPANSION
PLAN_BUILD
PLAN_VALIDATE
PLAN_COMPILE
STEP_EXECUTION
RESULT_VERIFY
RESULT_SYNTHESIS
RESULT_PUBLISH
FINALIZE
```

P4 must not copy a convenient subset of these names onto IAChatRun and then
report Frozen conformance.

## Gate Rule

There is no open P0 issue. The project_id conflict is not solved; it is bounded
and explicitly deferred. Source implementation may proceed only for the nine
Slices in the narrowed STEP 9 plan. Full P4 SRS/Frozen Agent Runtime acceptance
remains unavailable until P4-ISSUE-001, 003, 004, and 013 are addressed by an
approved later architecture decision.
