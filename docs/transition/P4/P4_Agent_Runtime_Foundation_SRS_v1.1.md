# P4 — NeX Agent Runtime Foundation SRS v1.1

**Status:** IMPLEMENTATION BASELINE — ARCHITECTURE CLOSURE APPLIED
**Supersedes:** `P4_Agent_Runtime_Foundation_SRS_v1.0.md`
**Branch:** `transition/p4-agent-runtime-foundation`

---

## 1. Purpose

P4 introduces the canonical Agent Runtime shell around the existing NeX Platform v1.0 Chat/RAG implementation.

```text
PROMPT
→ ExecutionTrigger
→ AgentExecution
→ RuntimeJob
→ ExecutableStep
→ existing Chat/RAG
→ AgentResult
→ ResultDelivery(PENDING)
```

P4 does not complete ResultDelivery publication ACK.

---

## 2. Higher Authority

```text
Integrated Frozen Set
> P4-CA01 Controlled Amendment once approved
> this SRS
> P4 Architecture Closure DEC-01~07
> P4 design/issue/traceability records
> implementation convenience
```

---

## 3. Mandatory Architecture Decisions

P4 SHALL implement DEC-01~DEC-07 from `P4_Architecture_Closure_DEC01_DEC07_v1.0.md`.

In particular:

- no IAChatRun;
- no IA-prefixed alternate RuntimeJob;
- no separate IA identity SoR;
- no Weekly Digest;
- canonical AgentResult is in P4;
- publication ACK remains deferred.

---

## 4. P4-CA01 Prerequisite

Canonical PROMPT admission SHALL NOT be enabled before P4-CA01 closes.

After amendment:

```text
PROMPT + IA
project_id = null | non-empty string

CLAIMED_WORKITEM
project_id = non-empty string

PA
project_id = non-empty string
```

No synthetic Project is permitted.

---

## 5. In Scope

- canonical `ae_agent_identity` for IA;
- principal-to-IA assignment;
- Workspace 1:N Conversation;
- append-only Conversation Message/Event journal;
- ExecutionTrigger(PROMPT);
- AgentExecution;
- RuntimeJob/Attempt;
- ExecutableStep;
- existing Chat/RAG adapter;
- AgentResult;
- required WORKSPACE_RESULT ResultDelivery in PENDING state;
- correlation/observability;
- disabled/shadow/required rollout;
- PostgreSQL/SQLite/Playwright/regression evidence.

---

## 6. Out of Scope

- IAChatRun;
- Weekly Digest / canonical Agent Memory;
- CLAIMED_WORKITEM behavior;
- CA/PA/EA execution;
- WC;
- NSL;
- WRITE;
- Approval;
- Enterprise OS;
- WA;
- Schedule;
- publication preflight/ACK/reconciliation.

---

## 7. Identity Rules

Mandatory:

```text
InteractionId       != AgentExecutionId
CX JobId            != RuntimeJobId
CX GenerationId     != ExecutableStepId
GeneratedResponseId != AgentResultId
request_id          != BusinessOperationId
```

No target ID is created by renaming a v1 ID.

---

## 8. AgentIdentity

### P4-REG-001
Use Frozen `ae_agent_identity`.

### P4-REG-002
IA execution requires:

```text
agent_type = IA
status = ACTIVE
```

### P4-REG-003
P4 SHALL NOT create `ae_ia_identities`.

### P4-REG-004
P4 MAY add `ae_ia_principal_assignment` for trusted principal→IA mapping.

### P4-REG-005
Browser-supplied `agent_id` is not authoritative.

---

## 9. Conversation / Journal

### P4-CONV-001
One Workspace MAY contain multiple Conversations.

### P4-CONV-002
Conversation has no Project binding.

### P4-CONV-003
Existing `chat_document_id` remains a compatibility/default Conversation identity during transition.

### P4-CONV-004
`ae_chat_interactions` remains the mutable v1.0 compatibility projection.

### P4-CONV-005
New Conversation messages/events are append-only for ordinary application behavior.

### P4-CONV-006
Raw prompt/response content remains in owner-private storage. PostgreSQL stores opaque ref/hash/size/lineage.

### P4-CONV-007
The journal SHALL NOT be described as canonical Agent Memory.

### P4-CONV-008
No Weekly Digest is implemented in P4.

---

## 10. ExecutionTrigger

### P4-TRG-001
P4 supports canonical:

```text
source_type = PROMPT
agent_type = IA
```

### P4-TRG-002
`source_ref` maps to the legacy InteractionId for the compatibility path.

### P4-TRG-003
After P4-CA01, `project_id` MAY be null for project-neutral IA PROMPT.

### P4-TRG-004
Duplicate trigger admission returns the same AgentExecution.

### P4-TRG-005
P4 does not implement CLAIMED_WORKITEM behavior.

---

## 11. AgentExecution

### P4-EXE-001
Introduce persistent canonical AgentExecution.

### P4-EXE-002
Key:

```text
(tenant_id, agent_execution_id)
```

### P4-EXE-003
AgentExecution references:

- agent_id/type;
- trigger id/type/ref;
- nullable project_id;
- workspace/conversation;
- legacy interaction;
- correlation/causation.

### P4-EXE-004
Use Frozen state vocabulary:

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

### P4-EXE-005
Use Frozen phase vocabulary:

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

P4 does not need to execute every future phase, but MUST NOT invent a competing phase/state enum.

### P4-EXE-006
Transitions use optimistic versioning or equivalent CAS semantics.

### P4-EXE-007
P4 MUST NOT transition to SUCCEEDED while required ResultDelivery is not ACKNOWLEDGED.

---

## 12. AgentExecution Physical Persistence Profile

P4 SHOULD add `ae_agent_execution` with at least:

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

Recommended constraints:

- primary key `(tenant_id, agent_execution_id)`;
- unique `(tenant_id, trigger_id)`;
- P4 PROMPT service admission only for IA;
- no cross-service FK.

---

## 13. RuntimeJob

### P4-JOB-001
Use Frozen `ae_runtime_job` / `ae_runtime_job_attempt`.

### P4-JOB-002
P4 implements:

```text
START_EXECUTION
CONTINUE_EXECUTION
```

Other Frozen job types remain reserved.

### P4-JOB-003
`execution_id` carries AgentExecutionId.

### P4-JOB-004
RuntimeJobId != CX JobId.

### P4-JOB-005
Use Frozen states:

```text
QUEUED
RUNNING
DONE
FAILED
CANCELLED
DEAD_LETTER
```

### P4-JOB-006
RUNNING requires current lease owner/token/until.

### P4-JOB-007
Stale lease completion is rejected.

### P4-JOB-008
Technical RuntimeJob retry does not create a new AgentExecution.

---

## 14. ExecutableStep

### P4-STEP-001
Introduce canonical ExecutableStep identity/persistence.

### P4-STEP-002
P4 uses one compatibility step that delegates to the extracted v1 Chat/RAG application service.

### P4-STEP-003
Do not duplicate CX retrieval/generation/MO/citation/artifact logic.

### P4-STEP-004
The step stores references, not raw prompt/response content.

### P4-STEP-005
Async terminalization uses CONTINUE_EXECUTION and must not re-run generation.

A minimal P4 persistence profile SHOULD include:

```text
tenant_id
executable_step_id
agent_execution_id
step_kind
state
legacy_interaction_id
retrieval_package_ref/hash nullable
cx_generation_id nullable
cx_job_id nullable
generated_response_id nullable
result_ref nullable
error_ref nullable
correlation_id
causation_id nullable
created_at
updated_at
```

---

## 15. Existing Chat/RAG Compatibility

Existing public Chat API remains backward compatible.

P4 SHALL:

- preserve InteractionId rules;
- preserve owner/workspace authorization;
- preserve CX/MO behavior;
- preserve async refresh/cancel/retry/recovery;
- preserve GeneratedResponse private storage/integrity;
- preserve Artifact linkage.

Routes SHOULD delegate to a reusable application service after refactor.

---

## 16. AgentResult

### P4-RES-001
Implement schema-valid canonical AgentResult.

### P4-RES-002
AgentResultId is new and immutable.

### P4-RES-003
For IA, WC claim lineage fields remain null/not-applicable.

### P4-RES-004
AgentResult references existing legacy GeneratedResponse/Artifact/Evidence identities.

### P4-RES-005
Persist complete `result_envelope_json` plus useful normalized columns.

### P4-RES-006
Use deterministic semantic `result_hash` from the P4 result design baseline.

### P4-RES-007
Legacy outcome mapping:

```text
COMPLETED              → SUCCEEDED or PARTIAL based on real quality state
NO_ANSWER              → BLOCKED
authoritative cancel   → CANCELLED
technical terminal fail→ FAILED
```

No fabricated success.

### P4-RES-008
P4 SHALL persist at most one canonical AgentResult per AgentExecution using a
database uniqueness constraint on `(tenant_id, agent_execution_id)`.

---

## 17. ResultDelivery P4 Foundation

### P4-DEL-001
Atomically with terminal AgentResult, create exactly one required:

```text
target_type = WORKSPACE_RESULT
target_ref = authoritative workspace_id
state = PENDING
```

### P4-DEL-002
No WC_WORK_RESULT in P4.

### P4-DEL-003
No publication preflight or ACK in P4.

### P4-DEL-004
Do not enqueue PUBLISH_RESULT in P4; the later publication phase creates publication jobs from durable PENDING deliveries.

### P4-DEL-005
PENDING delivery does not satisfy completion.

### P4-DEL-006
AgentExecution remains in Frozen pre-terminal publication phase/state and does not become SUCCEEDED.

### P4-DEL-007
The PENDING delivery SHALL already contain deterministic Frozen
`publication_operation_id` and `idempotency_key_ref`, derived from
`result_id + target_type + target_ref + result_hash`. A later publication
phase reuses those identities.

Expected P4 handoff point:

```text
state = RUNNING
phase = RESULT_PUBLISH
```

subject to direct Frozen Agent runtime confirmation.

P4-S7 SHALL close P4-ISSUE-026 before implementing the state mapping for
BLOCKED, FAILED, or CANCELLED AgentResult.

---

## 18. Persistence

All changes are additive.

Recommended tables:

```text
ae_agent_identity                       Frozen
ae_ia_principal_assignment              P4 mapping
ae_conversations
ae_conversation_messages
ae_conversation_events
ae_agent_execution
ae_runtime_job                          Frozen
ae_runtime_job_attempt                  Frozen
ae_executable_step
ae_agent_result                         Frozen-compatible
ae_result_delivery                      Frozen-compatible
```

Do not create:

```text
ae_ia_identities
ae_ia_personal_scopes
ae_ia_chat_runs
ae_ia_runtime_jobs
ae_ia_runtime_steps
ae_conversation_week_summaries
ae_conversation_week_heads
```

No cross-service FK. PostgreSQL DDL is canonical.

---

## 19. Rollout

```text
NEX_AE_AGENT_RUNTIME_MODE=disabled|shadow|required
```

### disabled
Legacy v1 only.

### shadow
Canonical wrapper runs when admission is possible. The route and wrapper share
one extracted Chat/RAG application-service invocation. A failure before legacy
invocation may fall back to that service once; a wrapper failure after
invocation starts MUST NOT invoke Chat/RAG or generation again. Wrapper failure
cannot replace a valid legacy response. Never report canonical SUCCEEDED
without ACK.

### required
Canonical IA, trigger, AgentExecution, RuntimeJob and step durability are mandatory.

Default remains disabled until P4 acceptance.

---

## 20. Observability

Trace when available:

```text
InteractionId
→ ExecutionTriggerId
→ AgentExecutionId
→ RuntimeJobId
→ ExecutableStepId
→ RetrievalPackageId
→ CX GenerationId
→ CX JobId
→ GeneratedResponseId
→ AgentResultId
→ ResultDeliveryId
```

No raw prompts, generated content, secrets, provider URLs/keys, DB URLs or raw evidence in runtime diagnostics.

---

## 21. Idempotency and Retry

- duplicate PROMPT trigger SHALL return the same AgentExecution;
- duplicate START/CONTINUE RuntimeJob enqueue SHALL use stable dedup keys;
- RuntimeJob retry stays inside the same AgentExecution;
- async continuation SHALL not recreate Interaction/CX Generation/CX Job/GeneratedResponse;
- duplicate AgentResult creation with identical semantics returns existing aggregate;
- same result identity with different semantics fails deterministically;
- P4 runtime idempotency SHALL NOT be described as NSL WRITE idempotency.

---

## 22. Security and Authority

- TenantId remains explicit and must not be inferred from Project/Org.
- IA comes from canonical AE Agent Registry.
- browser agent/project/tenant hints are not authoritative.
- project_id null means unresolved Project, not default/personal Project.
- existing v1.0 owner scope protections remain intact.
- no new direct provider access is introduced in AE.

---

## 23. Tests

Required:

- canonical AgentIdentity + principal assignment;
- project-null PROMPT after P4-CA01;
- CLAIMED_WORKITEM/PA project-null negative tests;
- AgentExecution idempotent admission;
- Frozen state/phase transitions;
- RuntimeJob dedup/lease/attempt/stale worker;
- Workspace 1:N Conversation;
- append-only journal / supersession / owner isolation;
- sync compatibility execution exactly once;
- async CONTINUE without generation replay;
- AgentResult schema/hash/immutability;
- AgentResult + PENDING delivery atomic rollback;
- duplicate result idempotency/conflict;
- attempted SUCCEEDED with PENDING delivery rejected;
- disabled/shadow/required modes;
- PostgreSQL restart smoke;
- existing Playwright Chat/RAG journey.

Boundary/robustness tests SHALL include concurrent first-prompt IA provisioning,
duplicate trigger races, lease expiry, stale completion, owner mismatch,
generated-response integrity failure, duplicate async continuation, and shadow
pre-invocation fallback/post-invocation wrapper failure with Chat/RAG and
provider call count fixed at one.

---

## 24. Quality

Repository gates remain:

```text
statement >= 95%
branch    >= 94%
```

Refactoring precedes feature work where route coupling prevents safe RuntimeJob invocation.

---

## 25. Implementation Sequence

```text
P4-CA01 Controlled Amendment + focused revalidation
P4-S1 Chat application-service refactor
P4-S2 canonical IA identity / assignment
P4-S3 Conversation 1:N / append-only journal
P4-S4 ExecutionTrigger / AgentExecution
P4-S5 RuntimeJob / Attempt
P4-S6 ExecutableStep / Chat-RAG adapter
P4-S7 AgentResult / PENDING ResultDelivery
P4-S8 observability / PostgreSQL smoke
P4-S9 closure
```

---

## 26. Acceptance

P4 closure requires:

```text
PROMPT
→ ExecutionTrigger
→ AgentExecution
→ RuntimeJob
→ ExecutableStep
→ existing Chat/RAG
→ AgentResult
→ required WORKSPACE_RESULT PENDING
```

plus:

- v1 regression PASS;
- P4-CA01 validation PASS;
- no fake Project;
- no alternate IA runtime;
- no Weekly Digest;
- no P5+ implementation;
- no false AgentExecution SUCCEEDED;
- PostgreSQL smoke PASS;
- relevant Playwright PASS;
- Frozen/amendment integrity documented.

---

## 27. Definition of Done

P4 is done when the canonical runtime foundation and durable result handoff exist and are regression-safe.

Publication ACK and terminal SUCCEEDED remain an explicit later-phase dependency.

The next phase SHALL reuse, not rename:

```text
AgentExecutionId
RuntimeJobId
ExecutableStepId
AgentResultId
```
