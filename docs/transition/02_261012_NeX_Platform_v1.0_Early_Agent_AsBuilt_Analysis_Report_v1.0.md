
# NeX Platform v1.0 Early Agent As-Built Analysis Report v1.0

**Phase:** P2 — Existing `nex-ae-api` Early Agent Detailed Analysis  
**Baseline:** `nurigitdev/2607_nex_platform` tag `v1.0`  
**Commit:** `ab7af0fc3b42225d1d71d20d517889d694a01c03`  
**Predecessor:** P1 — NeX Platform v1.0 As-Built Architecture Extraction — CLOSED  
**Important:** This report reconstructs the v1.0 early Agent **as implemented**. It does not yet map or score it against Agent v2.1.

---

## 1. Executive Summary

The v1.0 `nex-ae-api` Agent is not a general autonomous Agent Runtime. It is a **bounded, policy-driven user-request orchestrator** centered on workspace/chat interaction.

Its implemented canonical loop is:

```text
User Request
→ OA-backed owner scope
→ Workspace / Chat binding
→ Idempotent Interaction identity
→ Deterministic intent decision
→ Runtime policy resolution
→ Prompt contract resolution
→ optional CX Retrieval
→ Generation policy package
→ Synchronous or Asynchronous CX Generation
→ CX → MO provider execution
→ Quality / citation workflow
→ AE Chat result / GeneratedResponse / Artifact
→ Workspace activity + audit/observability
```

The implementation already separates multiple identities and lifecycle concerns:

```text
WorkspaceId
ChatDocumentId
InteractionId
RetrievalPackageId/Hash
CX Generation AdmissionId
CX GenerationId
CX JobId
GeneratedResponseId
ArtifactId / ArtifactVersionId
RequestId / TraceId
```

The most important finding is that v1.0 already contains a meaningful execution and recovery foundation:
- deterministic intent/mode policy
- explicit sync/async execution strategy
- durable async JobQueue
- idempotency and in-progress join/replay
- progress/cancel/retry/recovery
- terminal-state race reconciliation
- owner-scoped visibility
- result content integrity and lineage
- child-retry rather than source mutation

At the same time, it intentionally does **not** implement a generic multi-step plan/compile/skill/runtime model.

---

## 2. Agent Boundary

The repository's AE Agent contract explicitly states:

> The v1.0 Agent is a bounded orchestrator, not an unconstrained autonomous worker.

Implemented ownership:

```text
AE
= User intent
+ Execution mode
+ Runtime policy
+ Workspace / Chat
+ Prompt / Template contract
+ Retrieval orchestration
+ Final user-facing state
+ Result / Artifact lineage

CX
= Retrieval package
+ Grounded generation execution
+ Durable generation admission
+ Async generation Job
+ Generation evidence / citation metadata

MO
= Provider/model execution

OA
= User/service identity and authorization context

AG
= Operational/audit/governance projection
```

---

## 3. Two Independent Execution Dimensions

v1.0 separates **what kind of task is being performed** from **how generation is executed**.

### 3.1 Execution Mode

Actual canonical code modes in `intent_policy.py`:

```text
GENERAL_ANSWER
GROUNDED_ANSWER
DOCUMENT_SUMMARY
DOCUMENT_GENERATION
```

Resolution rules:

```text
Explicit execution_mode
→ wins deterministically

else
→ deterministic rule-based intent classifier

GENERAL_ANSWER + explicit retrieval request
→ GROUNDED_ANSWER
```

Properties:

- `retrieval_required = mode != GENERAL_ANSWER`
- `template_required = mode == DOCUMENT_GENERATION`
- each decision receives a stable `decision_hash`
- raw prompt is excluded from the decision record
- current classifier is deterministic/rule-based, not an LLM intent classifier

### 3.2 Execution Strategy

Independent generation strategy:

```text
SYNCHRONOUS
ASYNCHRONOUS
```

Default:

```text
generation.execution_strategy absent
→ SYNCHRONOUS
```

Therefore:

```text
Execution Mode
!=
Execution Strategy
```

A `DOCUMENT_GENERATION` or `GROUNDED_ANSWER` request can independently choose synchronous or asynchronous execution.

---

## 4. Documentation / Code Observation

The early design document lists conceptual modes including:

```text
DOCUMENT_SEARCH
ARTIFACT_TRANSFORM
```

However the implemented canonical intent policy accepts only the four modes listed above.

Interpretation for As-Built purposes:

- canonical Agent execution modes = four code-defined modes
- search and artifact transformation exist as separate platform/API capabilities
- they are not canonical values of the current `intent_policy.py` execution-mode enum

Classification:

> **P2-OBS-01 — documentation/code vocabulary drift; non-blocking As-Built observation**

No source change is made during P2.

---

## 5. Workspace / Chat Intake Model

### 5.1 Owner Scope

Browser requests derive owner authority from validated claims.

Canonical owner:

```text
TenantId
+
OwnerUserId
```

Service calls must provide explicit owner scope.

Canonical and compatibility owner identifiers must match or the request fails.

### 5.2 Workspace Binding

A Workspace contains:

```text
workspace_id
tenant_id
owner_user_id
chat_document_id
runtime_defaults
activity_count
last_activity_type
trace_id
request_id
timestamps
```

The workspace's `chat_document_id` is unique and a workspace-bound chat request cannot substitute a different chat document.

### 5.3 Interaction Identity

If not supplied:

```text
InteractionId
= UUID5("ae-interaction:" + trace_id + user_message_hash)
```

The user-message hash is SHA-256.

Idempotent interaction reuse requires all of these to remain compatible:

```text
same InteractionId
same owner
same WorkspaceId
same ChatDocumentId
same UserMessageHash
```

Otherwise:

```text
409 ae.chat_interaction_conflict
```

This is a strong input-binding rule.

---

## 6. ChatInteraction as the v1.0 User-Facing Execution Envelope

The durable table is:

```text
ae_chat_interactions
```

Canonical top-level statuses:

```text
PENDING
COMPLETED
NO_ANSWER
FAILED
```

Core durable fields include:

```text
InteractionId
WorkspaceId
TenantId
UserId / OwnerUserId
ChatDocumentId
Status
TraceId
RequestId
UserMessageHash
UserMessagePreview
CX Retrieval Package Id / Hash
CX GenerationId
CX Generation Status
Retrieval Summary JSON
Generation Summary JSON
Failure Summary JSON
timestamps
```

The ChatInteraction therefore combines:

- user-request identity
- owner scope
- workspace/conversation binding
- runtime policy/retrieval/generation summary
- user-facing lifecycle state

It is **not** the same object as the durable async Job.

---

## 7. Runtime Policy Resolution

After interaction binding:

```text
Intent Decision
→ Runtime Policy
→ Prompt Binding
→ Prompt Render Event
```

Runtime Policy resolves:

```text
execution_mode
template_ref
prompt_contract_ref
output_contract
artifact_intent
generation_profile
provider_capability
generation_parameters
quality_policy
```

It emits:

```text
policy_snapshot_hash
```

Important protections:

- user requests cannot inject raw provider URL/path/runtime fields
- unsupported generation parameters are rejected
- out-of-policy parameter values are rejected
- `DOCUMENT_GENERATION` requires an explicit template ID
- provider capability is a controlled alias/capability rather than raw endpoint

---

## 8. Generation Policy Package

Before CX generation, AE creates:

```text
ae_generation_policy_package.v1
```

It contains references/snapshots for:

```text
ExecutionMode
IntentDecisionRef
OwnerScope
TemplateRef
PromptContractRef
OutputContract
GenerationProfile
ProviderCapability
GenerationParameters
QualityPolicy
RetrievalPackageRef
SelectedEvidenceIds
UserMessageHash
PolicySnapshotHash
```

Privacy flags explicitly state:

```text
raw_user_prompt_included = false
raw_evidence_included = false
provider_runtime_included = false
raw_token_included = false
```

The package receives a deterministic `client_package_hash`.

---

## 9. Synchronous Execution Path

The synchronous path is:

```text
POST ChatInteraction
→ owner/workspace binding
→ save PENDING ChatInteraction
→ optional CX retrieval
   ├─ NO_ANSWER → terminal NO_ANSWER
   └─ usable evidence → continue
→ GenerationPolicyPackage
→ AE calls CX /api/v1/generations
→ CX performs grounded generation through MO
→ AE creates terminal ChatInteraction
→ COMPLETED or FAILED
→ prompt analytics / workspace activity
```

In the synchronous record the generation summary includes:

- provider capability / alias
- MO generation ID
- finish reason
- output preview
- usage
- grounded-response quality
- policy summary

The synchronous path is oriented around immediate ChatInteraction completion.

---

## 10. Asynchronous Execution Path

### 10.1 Admission

AE calls CX with:

```text
Idempotency-Key = "ae-chat:" + InteractionId
```

CX generation admission binds the key inside owner scope:

```text
TenantId
+ OwnerSubjectId
+ IdempotencyKeyHash
```

and derives:

```text
CX GenerationId
= UUID5(tenant + owner + idempotency key hash)
```

CX also hashes the semantic execution request.

If the same idempotency key is reused for a different semantic request:

```text
409 cx.generation_runtime.idempotency_conflict
```

### 10.2 Admission Decisions

Implemented admission semantics:

```text
NEW
RECLAIMED
JOIN
REPLAY
```

HTTP-level async admission projection:

```text
ENQUEUED
JOINED
REPLAYED
```

Meaning:

- identical in-progress work can be joined
- terminal matching work can be replayed
- expired in-progress leases can be reclaimed
- incompatible reuse fails closed

---

## 11. CX Durable Async Job

CX builds a common service Job:

```text
job_type = cx.grounded-generation.execute
```

Identity:

```text
JobId
= UUID5("cx-async-generation-job:" + CX GenerationId)
```

Job idempotency key:

```text
cx-async-generation:{CX GenerationId}
```

Maximum attempts default:

```text
3
```

Common job statuses:

```text
QUEUED
RUNNING
SUCCEEDED
FAILED
CANCELLED
```

The Job payload contains safe execution references only:

```text
CX GenerationId
AdmissionId
TenantRefId
OwnerSubjectRefId
RequestEnvelope SHA-256
RequestEnvelope Size
```

It explicitly excludes private prompt/evidence/output material.

---

## 12. JobQueue Reliability

The common JobQueue already supports:

- idempotent enqueue by `job_type + idempotency_key`
- duplicate JobId rejection
- claim/lock
- PostgreSQL locking
- status transition under row lock
- retry decision
- exponential backoff using `available_at`
- dead-letter
- cancel
- replay as **new Job**

Retry rule:

```text
RUNNING failure
+ retryable
+ attempt_count < max_attempts
→ REQUEUE

else
→ DEAD_LETTER
```

Dead-letter replay never mutates the failed source Job.

---

## 13. AE Async Projection

AE does not copy the private CX Job payload.

It keeps a safe projection:

```text
execution_strategy
lifecycle_status
admission_status
job_id
cx_generation_id
cx_job_status
attempt_count
max_attempts
retryable
handoff_status
next_action
safe error
safe links
owner_scope_enforced = true
content_included = false
```

This is an important boundary:

```text
AE ChatInteraction
!=
CX Job
```

---

## 14. AE Async State Machine

### 14.1 CX Job statuses

```text
QUEUED
RUNNING
SUCCEEDED
FAILED
CANCELLED
```

### 14.2 CX Handoff statuses

```text
PENDING
READY
BLOCKED
```

### 14.3 AE lifecycle

```text
PENDING
COMPLETED
BLOCKED
```

Critical completion rule:

```text
CX Job = SUCCEEDED
alone
!= AE COMPLETED
```

Instead:

```text
CX Job = SUCCEEDED
AND Handoff = READY
→ AE lifecycle = COMPLETED
→ next_action = PRESENT_GENERATION_TO_OWNER
```

If:

```text
Job FAILED/CANCELLED
→ BLOCKED
→ RETRY_OR_REVIEW_GENERATION
```

`SUCCEEDED + Handoff not READY` remains `PENDING`.

This shows that v1.0 distinguishes provider/job completion from result readiness.

---

## 15. Chat Status Mapping

Async lifecycle is projected into the top-level ChatInteraction:

```text
AE lifecycle PENDING
→ Chat PENDING

AE lifecycle COMPLETED
→ Chat COMPLETED

AE lifecycle BLOCKED
→ Chat FAILED
```

There is no separate top-level Chat `CANCELLED` status in the current As-Built DB enum.

Cancellation is represented through async generation metadata and maps the user-facing Chat result to the existing terminal failure model where applicable.

---

## 16. Progress Model

Progress response:

```text
ae_generation_progress.v1
```

Example stage projection:

```text
QUEUED    → MO_ADMISSION_WAITING
RUNNING   → GENERATING
SUCCEEDED → FINALIZING
COMPLETED → COMPLETED
FAILED    → GENERATION_FAILED
CANCELLED → CANCELLED
```

Privacy rules:

```text
content_included = false
raw_failure_detail_included = false
```

Polling:

```text
non-terminal → next_poll_after_seconds = 2
terminal     → no poll
```

---

## 17. Cancellation Semantics

Cancellation is not a blind state overwrite.

Behavior:

```text
already CANCELLED
→ ALREADY_CANCELLED

terminal AE lifecycle
→ not cancellable

QUEUED/RUNNING
→ ask CX to cancel
```

Important race handling:

If cancellation loses a race to CX terminal completion:

```text
CX job transition conflict
→ force lifecycle refresh/reconciliation
→ TERMINAL_STATE_WON
```

Therefore:

```text
Cancel request
!= unconditional CANCELLED
```

The actual terminal source state wins.

---

## 18. Recovery / Retry Semantics

Recovery policy:

```text
PENDING
→ WAIT

COMPLETED
→ NONE

BLOCKED + retryable
→ RETRY_AS_CHILD

BLOCKED + nonretryable
→ REVIEW_REQUIRED
```

Retry requires:

```text
new InteractionId
same original input hash
parent lineage
```

Retry with the same `InteractionId` is rejected.

Input drift is rejected:

```text
submitted input hash != parent UserMessageHash
→ 409 ae.async_generation.retry_input_mismatch
```

Retry lineage captures:

```text
ParentInteractionId
ParentJobId
ParentCXGenerationId
ParentResponseId
```

This makes Retry an explicit child execution rather than mutation of the source attempt.

---

## 19. GeneratedResponse Identity and Delivery Readiness

When CX handoff becomes `READY`, AE prepares a durable GeneratedResponse.

Identity:

```text
ResponseId
= UUID5(
    InteractionId
    + CX GenerationId
    + Content SHA-256
  )
```

Lineage includes:

```text
ResponseId
LineageType = ORIGINAL | RETRY_CHILD
InteractionId
ChatDocumentId
CX GenerationId
CX JobId
ContentType
Content SHA-256
Size
Retrieval Package Id / Hash
Structured Draft Id
Citation Workflow Status
Grounding Lineage
ParentInteractionId
ParentResponseId
```

The public lineage excludes:

```text
raw content
storage reference
private evidence
```

---

## 20. Generated Response Storage

Generated response content is private and integrity-checked.

Storage modes include:

```text
Memory
Filesystem
S3/Object Storage
```

Logical storage reference:

```text
ae://chat-responses/...
```

Integrity requires:

```text
Content SHA-256
+
Size
+
Expected deterministic storage ref
```

The save sequence is designed so that if the chat record update fails after newly writing response content, AE attempts to delete the newly created content.

The response API returns content only after:

- owner-visible ChatInteraction exists
- GeneratedResponse lineage exists
- storage payload is present
- digest/size verification passes

---

## 21. Result Lineage and Citation Quality

GeneratedResponse completion is tied to citation/grounding validation.

For grounded output, lineage checks include:

```text
RetrievalPackageId
RetrievalPackageHash
SelectedEvidenceCount
ProviderPromptPackageHash
CitationValidationStatus
RepairAttempt state/count
```

A mismatched lineage is rejected.

The implementation therefore treats a user-facing result as more than raw LLM text.

---

## 22. Artifact Linkage

Artifacts are separate objects linked back to ChatInteraction.

Artifact reference de-duplication uses:

```text
ArtifactId
+
ArtifactVersionId
```

The linkage validates:

```text
same ChatDocumentId
same InteractionId
```

Artifact references include:

- display title/type/status
- primary/available formats
- preview/download routes
- source generation ID/content hash
- quality summary
- allowed actions

---

## 23. P2 Identity Model

The v1.0 Early Agent identity chain is:

```text
TenantId
OwnerUserId
    │
    ▼
WorkspaceId
    │
    ├── ChatDocumentId
    │
    ▼
InteractionId
    │
    ├── RequestId
    ├── TraceId
    ├── UserMessageHash
    │
    ├── RetrievalPackageId / Hash
    │
    ▼
CX Generation AdmissionId
    │
    ▼
CX GenerationId
    │
    ▼
CX JobId
    │
    ▼
GeneratedResponseId
    │
    └── ArtifactId / ArtifactVersionId
```

Important:

```text
InteractionId
!= CX GenerationId
!= CX JobId
!= GeneratedResponseId
```

---

## 24. Execution Unit Interpretation

Based only on v1.0 source:

### User-facing execution unit

```text
ChatInteraction
```

It owns:
- request attempt
- user-facing state
- policy/retrieval/generation summary
- workspace activity
- result/artifact linkage

### Durable generation execution unit

```text
CX Job
```

It owns:
- background generation execution status
- attempt/retry/dead-letter
- worker claim
- durable asynchronous execution

### Business/general Agent execution unit

Not present as a generic abstraction in v1.0.

There is no source-supported generic model in P2 equivalent to:

```text
generic AgentExecution
generic multi-step Plan
generic ExecutableStep
generic Skill execution
multi-agent work coordination
scheduled autonomous Agent
external business-system action execution
```

The v1.0 design document explicitly defers autonomous multi-step domain Agent, scheduled background assistant and external business-system actions.

---

## 25. State Machines Summary

### ChatInteraction

```text
PENDING
├─→ COMPLETED
├─→ NO_ANSWER
└─→ FAILED
```

### CX Job

```text
QUEUED
→ RUNNING
├─→ SUCCEEDED
├─→ FAILED
└─→ CANCELLED

RUNNING failure
├─ retry eligible → QUEUED with available_at
└─ exhausted      → FAILED / dead-letter
```

### AE Async lifecycle

```text
PENDING
├─ Job SUCCEEDED + Handoff READY → COMPLETED
└─ Job FAILED/CANCELLED          → BLOCKED
```

### Recovery

```text
PENDING      → WAIT
COMPLETED    → NONE
BLOCKED
 ├─ retryable     → RETRY_AS_CHILD
 └─ nonretryable  → REVIEW_REQUIRED
```

---

## 26. Failure and Fail-Closed Behavior

Examples found in v1.0:

- Workspace/owner mismatch → not found/conflict
- Interaction ID reused with different input → conflict
- unsupported execution mode → reject
- provider runtime fields from user → reject
- invalid generation parameters → reject
- retrieval `NO_ANSWER` → no unsupported generation
- missing durable async Job → 503 retryable
- async Job/Handoff lineage mismatch → contract error
- owner mismatch on CX Job visibility → not found
- same idempotency key + different semantic request → conflict
- GeneratedResponse digest/size mismatch → integrity failure
- Retry input mismatch → conflict
- Retry reusing same InteractionId → reject
- terminal result cannot be blindly cancelled
- cancellation race → terminal state reconciliation

---

## 27. Test Evidence for the Early Agent

The repository contains dedicated tests for:

- async chat admission
- cancel/retry
- async contract validation
- async refresh
- CX async generation boundary
- PostgreSQL async generation smoke
- durable workspace/chat orchestration
- owner scope
- generated response contracts
- generated response lineage
- generated response storage
- generation lifecycle contracts
- lifecycle observability
- lifecycle PostgreSQL smoke
- generation recovery orchestration
- runtime policy
- intent policy
- workspace persistence
- CX async worker/recovery/operations

This confirms that the early Agent lifecycle is a deliberate implementation area rather than incidental chat glue.

---

## 28. P2 As-Built Architecture

```text
User / Browser
     │
     ▼
NeX-AE Web
     │
     ▼
┌──────────────────────────────────────┐
│              NeX-AE API              │
│                                      │
│ Owner Scope / Workspace              │
│        ↓                             │
│ ChatInteraction                     │
│        ↓                             │
│ Deterministic Intent                │
│        ↓                             │
│ Runtime Policy / Prompt Contract    │
│        ↓                             │
│ Retrieval Orchestration ────────┐   │
│        ↓                        │   │
│ Generation Policy Package       │   │
│        ↓                        │   │
│ Sync / Async Strategy           │   │
└────────┬────────────────────────┘   │
         │                            │
         ▼                            │
┌──────────────────────────────┐      │
│            NeX-CX            │◄─────┘
│ Retrieval Package            │
│ Generation Admission         │
│ CX GenerationId              │
│ Durable CX Job               │
│ Worker / Retry / Handoff     │
└─────────────┬────────────────┘
              │
              ▼
        ┌─────────────┐
        │   NeX-MO    │
        │ Provider    │
        │ Generation  │
        └─────────────┘
              │
              ▼
         CX Handoff
              │
              ▼
┌──────────────────────────────────────┐
│              NeX-AE API              │
│ Async Lifecycle                     │
│ Citation / Grounding Validation     │
│ GeneratedResponse                   │
│ Private Response Storage            │
│ Artifact Linkage                    │
│ Workspace Activity                  │
└──────────────────────────────────────┘
```

---

## 29. P2 Findings

### Strong existing foundations

1. Owner-scoped execution context
2. Stable Interaction identity
3. Idempotent request binding
4. Deterministic intent decision
5. Policy snapshot and hash
6. Provider abstraction
7. Retrieval/evidence binding
8. Durable async Job
9. Retry/dead-letter infrastructure
10. Job/result identity separation
11. Completion vs Handoff readiness separation
12. Child-retry lineage
13. Cancellation-race reconciliation
14. GeneratedResponse identity/integrity
15. Result/artifact lineage
16. Cross-service trace/request IDs
17. Rich automated tests

### Bounded scope of current Agent

The current implementation remains intentionally centered on:

```text
one user request
→ one bounded orchestration
→ retrieval/generation
→ one user-facing result/artifact
```

It does not yet generalize this into arbitrary multi-step enterprise work execution.

---

## 30. P2 Observations Register

| ID | Observation | P2 Treatment |
|---|---|---|
| P2-OBS-01 | Early design doc names `DOCUMENT_SEARCH` / `ARTIFACT_TRANSFORM` as modes, while code canonical intent modes are four values. | Record As-Built code vocabulary; no source change |
| P2-OBS-02 | Top-level Chat status has no distinct `CANCELLED`; cancellation is carried in async lifecycle and projected to current Chat terminal model. | Record As-Built behavior |
| P2-OBS-03 | Async result lifecycle is richer than synchronous result lifecycle: async has explicit durable response content + lineage/handoff path. | Preserve for later transition analysis |
| P2-OBS-04 | Durable execution Job is CX generation-specific, not a generic Agent execution object. | Key later transition input |
| P2-OBS-05 | `ChatInteraction` combines request attempt and user-facing execution state, but is not a general-purpose Agent execution object. | Key later transition input |

These are not defects in P2. They are facts to carry into later transition analysis.

---

## 31. P2 Exit Gate

- [x] Chat/Workspace identity reconstructed
- [x] Owner/tenant binding reconstructed
- [x] Intent decision path reconstructed
- [x] Runtime policy path reconstructed
- [x] Sync/async strategy reconstructed
- [x] Retrieval/generation orchestration reconstructed
- [x] CX async admission/idempotency reconstructed
- [x] Durable Job semantics reconstructed
- [x] Progress state reconstructed
- [x] Cancel/race behavior reconstructed
- [x] Recovery/retry behavior reconstructed
- [x] Result identity/storage reconstructed
- [x] Artifact/result lineage reconstructed
- [x] Persistent DB model inspected
- [x] Test coverage surface inspected
- [x] No Agent v2.1 comparison performed prematurely

## P2 Status

> **P2 — Existing `nex-ae-api` Early Agent Detailed Analysis: CLOSED**

---

## 32. Next Phase

Proceed to:

> **P3 — NSL v0.1 As-Built Analysis**

Baseline:

```text
repository = nurigitdev/2608_nsl
tag        = v0.1
SHA        = 803f22aadc3946a48b05472c80b60fe11d9d9554
```

P3 must first reconstruct NSL v0.1 independently before comparing it with NSL v0.2.
