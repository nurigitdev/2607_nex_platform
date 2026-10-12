# P4 Source Audit and Implementation Plan v1.1

**Status:** PRE-IMPLEMENTATION BASELINE
**Supersedes:** `P4_Source_Audit_and_Implementation_Plan_v1.0.md`

## 1. Mandatory Pre-Step — P4-CA01

Before source implementation:

1. apply Project-Neutral PROMPT Controlled Amendment;
2. validate amended ExecutionTrigger schema/protocol;
3. run focused E1 + E2E-01 + trigger probes;
4. publish amendment/re-freeze addendum.

## 2. Target Domain

```text
AgentIdentity                 Frozen ae_agent_identity
IAPrincipalAssignment         AE-local mapping
Conversation
ConversationMessage
ConversationEvent
ExecutionTrigger
AgentExecution
RuntimeJob
RuntimeJobAttempt
ExecutableStep
AgentResult
ResultDelivery(PENDING)
```

Legacy ChatInteraction/CX/GeneratedResponse/Artifact retain current meanings.

Removed:

```text
IAChatRun
IARuntimeJob
IARuntimeStep
ae_ia_identities
IAPersonalScope
ConversationWeeklyDigest
```

## 3. Additive Database Plan

### 2001 — Agent Registry adoption + IA principal assignment

Use/create Frozen-equivalent:

```text
ae_agent_identity
```

Add:

```text
ae_ia_principal_assignment
```

No duplicate IA identity table.

### 2002 — Conversation + append-only journal

```text
ae_conversations
ae_conversation_messages
ae_conversation_events
```

No `project_id`.

Keep `ae_workspaces.chat_document_id` as rollback/default pointer.

### 2003 — AgentExecution

```text
ae_agent_execution
```

Minimum fields:

```text
tenant_id
agent_execution_id
agent_id
agent_type
trigger_id
source_type
source_ref
project_id nullable
workspace_id nullable
conversation_id nullable
legacy_interaction_id nullable
state
phase
version
result_id nullable
correlation_id
causation_id nullable
created_at
updated_at
```

### 2004 — RuntimeJob

Adopt Frozen:

```text
ae_runtime_job
ae_runtime_job_attempt
```

### 2005 — ExecutableStep

Add canonical step persistence referencing AgentExecution.

### 2006 — AgentResult / pending delivery

Adopt Frozen-compatible:

```text
ae_agent_result
ae_result_delivery
```

Persist complete result envelope and one required PENDING WORKSPACE_RESULT.

Enforce one AgentResult per AgentExecution. Set `target_ref` to the trusted
workspace identity and derive Frozen `publication_operation_id` and
`idempotency_key_ref` before the atomic insert, even though P4 creates no
publication job.

## 4. Implementation Slices

### P4-S1 — Chat Application-Service Refactor
Extract reusable create/refresh/cancel/recovery orchestration. Routes stay HTTP
adapters. Establish the single-invocation seam used by legacy and shadow
paths. Regression PASS.

### P4-S2 — Canonical IA Identity
Implement canonical IA AgentIdentity plus principal assignment and concurrency-safe lazy provisioning.

### P4-S3 — Conversation 1:N + Journal
Introduce project-neutral Conversation and append-only messages/events. Keep mutable v1 interaction projection. No digest.

### P4-S4 — Canonical AgentExecution Admission
Use amended ExecutionTrigger(PROMPT, nullable Project), idempotent trigger→AgentExecution, Frozen state/phase, rollout modes.

### P4-S5 — Canonical RuntimeJob
Use Frozen runtime job/attempt. Implement START_EXECUTION and CONTINUE_EXECUTION, lease/token/expiry/stale-worker rejection. Checkpoint Gate.

### P4-S6 — ExecutableStep + Existing Chat/RAG
Create compatibility step. Invoke the extracted application service exactly
once. Shadow fallback is allowed only before that invocation starts. Async
continuation uses CONTINUE_EXECUTION and never replays generation.

### P4-S7 — AgentResult
Map terminal legacy outcome to one immutable AgentResult per execution. Compute
result_hash. Atomically create one PENDING WORKSPACE_RESULT delivery with
trusted workspace target and stable publication identities. Close
P4-ISSUE-026 from cited Frozen state semantics before coding non-success state
mapping. No ACK.

### P4-S8 — Observability / PostgreSQL Smoke
Trace full identity chain, protected restart/lease/idempotency smoke, privacy scan, excluded-scope scan.

### P4-S9 — Closure
Full Gate, PostgreSQL smoke, existing Playwright journey, Frozen/amendment integrity, prove no SUCCEEDED without ACK.

## 5. Rollout

```text
NEX_AE_AGENT_RUNTIME_MODE=disabled|shadow|required
```

- disabled: legacy v1 only.
- shadow: canonical wrapper when admission succeeds; legacy Chat/RAG is invoked
  at most once across wrapper/fallback paths; wrapper failure cannot replace a
  valid legacy response; no false SUCCEEDED.
- required: canonical IA/Trigger/Execution/Job durability mandatory.

## 6. Exit Gate

```text
PROMPT
→ canonical ExecutionTrigger
→ canonical AgentExecution
→ canonical RuntimeJob
→ canonical ExecutableStep
→ existing Chat/RAG
→ canonical AgentResult
→ required WORKSPACE_RESULT delivery PENDING
```

Required also:

- v1 regression PASS
- no fake Project
- no IAChatRun parallel model
- no Weekly Digest
- no P5+ scope
- no AgentExecution SUCCEEDED without ACK
