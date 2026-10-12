
# P4 — NeX Agent Runtime Foundation SRS v1.0

**Document Status:** IMPLEMENTATION BASELINE — P4  
**Target Branch:** `transition/p4-agent-runtime-foundation`  
**As-Built Baseline:** NeX Platform v1.0 tag `v1.0` (`ab7af0fc3b42225d1d71d20d517889d694a01c03`)  
**Target Semantic Baseline:** NeX Platform v2.1 + NeX Agent v2.1 + NSL v0.2 Integrated Frozen Set  
**Frozen Root:** `docs/frozen/v2.1/`  
**Transition Root:** `docs/transition/`  
**Primary Purpose:** Preserve NeX Platform v1.0 Chat/RAG behavior while introducing the canonical Agent Runtime foundation required for later NSL/WC/WRITE integration.

---

# 1. Purpose

This SRS defines the implementation scope and acceptance criteria for **P4 — Agent Runtime Foundation**.

P4 is a **transition phase**, not a full v2.1 implementation.

The intent is to place a canonical Agent Runtime shell around the already-implemented v1.0 Chat/RAG path without replacing, renaming, or semantically collapsing existing v1.0 identities and persistence.

Canonical transition direction:

```text
PROMPT
→ AgentExecution
→ AE RuntimeJob
→ Compatibility ExecutableStep
→ existing v1.0 Chat/RAG execution
→ AgentResult foundation
→ ResultDelivery foundation
```

The v1.0 implementation remains the working behavior baseline.

The Frozen v2.1/Agent v2.1/NSL v0.2 document set remains the target semantic authority.

---

# 2. Normative Language

The keywords **MUST**, **MUST NOT**, **SHALL**, **SHALL NOT**, **SHOULD**, **SHOULD NOT**, and **MAY** are normative in this SRS.

When this SRS references a Frozen document or machine-readable contract, that Frozen source remains the higher semantic authority.

This SRS does not amend the Frozen Set.

---

# 3. Authority and Reading Order

Before modifying source code, the implementer SHALL read:

1. `docs/frozen/v2.1/README_FROZEN_BASELINE.md`
2. the P4 Priority-A Frozen documents identified by that README
3. the Agent↔NSL Integration Contract identified by that README
4. the Result Publication hardening README identified by that README
5. `docs/transition/00` through `docs/transition/05` in order
6. this SRS
7. the current branch source code

Conflict rule:

```text
Frozen semantic authority
> this P4 SRS
> transition analysis/guidance
> implementation convenience
```

Current source code is authoritative only for **what v1.0 actually does**, not for the v2.1 target semantics.

---

# 4. Input Baselines

## 4.1 As-Built Inputs

P4 uses these transition records as the As-Built interpretation:

- `00_261012_NeX_AsBuilt_Baseline_Record_v1.0.md`
- `01_261012_NeX_Platform_v1.0_AsBuilt_Architecture_Extraction_Report_v1.0.md`
- `02_261012_NeX_Platform_v1.0_Early_Agent_AsBuilt_Analysis_Report_v1.0.md`
- `03_261012_NSL_v0.1_AsBuilt_Architecture_and_Runtime_Analysis_Report_v1.0.md`
- `04_261012_NSL_v0.1_to_v0.2_Delta_and_Implementation_Plan_v1.0.md`
- `05_261012_NeX_v1.0_to_v2.1_Frozen_Mapping_and_Delta_Consolidation_v1.0.md`

## 4.2 Frozen Target Inputs

P4 implementation SHALL conform to the Frozen authority hierarchy described in `README_FROZEN_BASELINE.md`.

Particularly relevant normative assets include:

### Agent runtime semantic authority
- Frozen Agent v2.1 Runtime DOCX set
- Unified Agent Loop / AgentExecution state machine
- Intent Resolution
- Context Builder
- Plan Builder
- Deterministic Compiler
- StepExecutionEngine
- Wait/Resume/Retry/Reconciliation
- Result Verification/Aggregation/Presentation
- Runtime Event/Memory
- Integrated E2E Runtime baseline

### Platform machine-readable authority
Batch02 CP02/CP06:
- `AE/001_ae_agent_registry.sql`
- `AE/003_ae_runtime_job_v2_1.sql`
- `AE/agent-identity-v2.1.schema.json`
- `AE/agent-session-v2.1.schema.json`
- `AE/execution-trigger-v2.1.schema.json`
- `AE/runtime-job-v2.1.schema.json`
- `AE/runtime-job-attempt-v2.1.schema.json`
- `AE/agent_registry_v2_1.py`
- `AE/execution_trigger_v2_1.py`
- `AE/reliability_protocols_v2_1.py`

Batch08 Result Publication:
- `AE_PUBLICATION/005_ae_result_publication_v2_1.sql`
- `AE_PUBLICATION/agent-result-v2.1.schema.json`
- `AE_PUBLICATION/result-delivery-v2.1.schema.json`
- `AE_PUBLICATION/result-publication-preflight-v2.1.schema.json`

Step8 Consolidation:
- canonical `ExecutionTrigger = PROMPT | CLAIMED_WORKITEM`
- no direct Event/Schedule new-execution trigger
- final package-trust and background-result rules

---

# 5. P4 Goals

P4 SHALL achieve the following goals.

## P4-GOAL-01 — Canonical Agent Identity Foundation

Introduce NeX-AE Agent Registry persistence and interfaces compatible with the Frozen `AgentIdentity v2.1` contract.

P4 runtime execution uses **IA only**.

CA/PA/EA registry support MAY exist structurally because the Frozen schema includes them, but P4 MUST NOT implement their work-claim execution behavior.

## P4-GOAL-02 — Canonical AgentExecution Shell

Introduce a new canonical `AgentExecutionId` and execution aggregate around the current v1.0 prompt-driven Chat/RAG path.

## P4-GOAL-03 — Canonical AE RuntimeJob

Introduce a distinct AE RuntimeJob persistence/queue contract conforming to Frozen RuntimeJob v2.1.

## P4-GOAL-04 — Compatibility ExecutableStep

Represent the current v1.0 bounded Chat/RAG orchestration as a compatibility step under the new AgentExecution.

P4 SHALL NOT rewrite the mature retrieval/generation path merely to resemble the target architecture.

## P4-GOAL-05 — AgentResult Foundation

Produce an immutable AgentResult record that references existing v1.0 GeneratedResponse/Artifact/Evidence identities without renaming those identities.

## P4-GOAL-06 — Completion Safety

Do not mark AgentExecution terminal `SUCCEEDED` unless the Frozen completion rule is satisfied.

A durable AgentResult alone is not sufficient if required ResultDelivery acknowledgements are not implemented.

## P4-GOAL-07 — v1.0 Compatibility

Existing public Chat/RAG behavior SHALL remain backward compatible when P4 is disabled and SHOULD remain user-visible compatible when P4 shadow/compatibility mode is enabled.

## P4-GOAL-08 — Future-Safe Extension Points

The implementation SHALL reserve clean extension points for:

- NSLExecutionId
- BusinessOperationId
- Wait/Resume
- WC WorkItem/Claim
- Result Publication
- Reconciliation
- Approval
- Schedule

without implementing those later-phase semantics now.

---

# 6. Explicit P4 Scope

## 6.1 In Scope

P4 includes:

- `AgentIdentity` repository/service foundation
- IA agent admission
- `ExecutionTrigger` support for `PROMPT`
- `AgentExecution` persistence/domain model
- `RuntimeJob` / `RuntimeJobAttempt`
- START_EXECUTION processing
- compatibility ExecutableStep
- existing Chat/RAG invocation through an adapter
- AgentResult persistence foundation
- ResultDelivery persistence foundation sufficient to prevent invalid success transitions
- runtime correlation/causation propagation
- transition feature flag / rollout mode
- compatibility and regression tests
- observability required to trace the wrapper path

## 6.2 Out of Scope

P4 MUST NOT implement:

- `CLAIMED_WORKITEM` execution behavior
- WC WorkItem
- WC Routing/Assignment/Claim
- CA / PA / EA background execution
- NSL runtime integration
- NSL READ Skill execution
- NSL WRITE
- NSL approval
- Agent FORMAL_APPROVAL
- Human approval workflow
- BusinessOperationId WRITE semantics
- Enterprise OS transaction WRITE
- WA WorkActivity/WorkAsset publication
- Recurring Work / Schedule
- production publication reconciliation
- UNKNOWN_COMMIT_STATE reconciliation
- external email/messenger/notification fan-out
- semantic redesign of CX/MO provider execution
- broad reorganization of existing v1.0 services

---

# 7. Non-Goals

P4 is not a project to:

- replace `ChatInteraction`
- replace `CX GenerationId`
- replace `CX JobId`
- replace `GeneratedResponseId`
- redesign all Agent v2.1 modules
- build autonomous multi-step domain agents
- build a generic workflow engine
- move RAG generation responsibility across services
- implement the whole Platform v2.1 Frozen Set in one branch

---

# 8. Identity Invariants

The following invariants are mandatory.

## P4-ID-001

`InteractionId` SHALL remain a v1.0 interaction identity.

`InteractionId` MUST NOT be renamed or reused as `AgentExecutionId`.

## P4-ID-002

`CX JobId` MUST NOT be reused as `AE RuntimeJobId`.

Both identities may coexist in the same end-to-end trace.

## P4-ID-003

`CX GenerationId` MUST NOT be reused as:

- `AgentExecutionId`
- `ExecutableStepId`
- `NSLExecutionId`

## P4-ID-004

`GeneratedResponseId` MUST NOT be reused as `AgentResultId`.

## P4-ID-005

`request_id` MUST NOT be reused as `BusinessOperationId`.

P4 does not create WRITE BusinessOperation semantics.

## P4-ID-006

`trace_id` MAY be mapped to `correlation_id` when the existing v1.0 trace ID already represents the same cross-service correlation scope.

This mapping SHALL be explicit in code and tests.

## P4-ID-007

`causation_id` SHALL remain nullable unless a real causation identity exists.

Do not manufacture causation from unrelated request fields.

## P4-ID-008

`AgentExecutionId` SHALL be a new identity.

Idempotent trigger re-admission SHALL return the existing execution rather than create a second one.

## P4-ID-009

`RuntimeJobId` SHALL be a new AE runtime identity stored in `ae_runtime_job`.

## P4-ID-010

`ExecutableStepId` SHALL be a new identity independent of existing CX identities.

## P4-ID-011

`AgentResultId` SHALL be a new identity independent of GeneratedResponse/Artifact identities.

---

# 9. Known Transition Constraints

These constraints are source-derived and SHALL be treated explicitly.

## P4-CONSTRAINT-01 — PROMPT project_id

Frozen `execution-trigger-v2.1.schema.json` requires `project_id` even for `PROMPT`.

v1.0 generic Chat does not necessarily guarantee trusted project context for every interaction.

Therefore:

- P4 MUST NOT synthesize a fake `project_id`.
- P4 MUST NOT infer TenantId from Org/Project.
- P4 MUST resolve project context only from a trusted server-side source.
- if trusted project context is unavailable, the runtime wrapper behavior SHALL follow the rollout mode defined in Section 22.
- strict mode SHALL fail deterministically rather than invent project scope.

## P4-CONSTRAINT-02 — IA Agent Provisioning

Frozen Agent Registry is authoritative for `agent_id`.

P4 MUST NOT accept arbitrary browser-supplied Agent identity as authority.

P4 implementation SHALL use an injected/resolved active IA `AgentIdentity`.

Automatic IA provisioning policy is not defined by the Frozen machine-readable contracts available to this SRS and SHALL NOT be invented silently.

Tests MAY seed an active IA identity.

## P4-CONSTRAINT-03 — AgentExecution Machine-Readable Schema Gap

The Frozen Set contains machine-readable contracts for AgentIdentity, ExecutionTrigger, RuntimeJob and AgentResult, but the P4 inspection did not identify an equivalent standalone machine-readable `AgentExecution` schema in the normative contract directory.

Therefore:

- the semantic state/phase vocabulary SHALL be taken directly from the Frozen Agent v2.1 AgentExecution State Machine document.
- the P4 implementation plan MUST list the exact extracted state/phase vocabulary before coding.
- P4 SHALL NOT invent a competing semantic enum.
- physical DB columns MAY use `text` without a narrower DB CHECK if necessary to avoid freezing an incorrect subset.

## P4-CONSTRAINT-04 — Result Publication Completion Gate

Frozen Result Publication hardening states:

```text
AgentExecution may enter SUCCEEDED
only after:
  AgentResult is durable
  AND all required ResultDelivery objects are ACKNOWLEDGED
```

P4 does not implement the full v2.1 publication control plane.

Therefore P4 MUST NOT declare canonical AgentExecution success merely because the legacy Chat interaction completed.

## P4-CONSTRAINT-05 — OA Publication Preflight

Frozen `ResultPublicationPreflight v2.1` requires AS_OF_NOW authorization and scope/classification/visibility checks.

P4 SHALL NOT fake these checks.

If P4 does not implement a fully conformant publication preflight, required ResultDelivery SHALL remain non-acknowledged and AgentExecution SHALL remain in the appropriate Frozen pre-terminal/finalization state.

The existing v1.0 user-facing Chat response MAY still complete because legacy UX compatibility is separate from canonical AgentExecution completion.

---

# 10. Target P4 Architecture

```text
Browser / AE-Web
       │
       ▼
Existing POST /api/v1/chat/interactions
       │
       ├─ existing owner/workspace validation
       ├─ existing InteractionId
       │
       ▼
P4 Runtime Admission Adapter
       │
       ├─ resolve Tenant
       ├─ resolve active IA AgentIdentity
       ├─ resolve trusted Project context
       └─ build PROMPT ExecutionTrigger
       │
       ▼
AgentExecution                     NEW
       │
       ▼
START_EXECUTION RuntimeJob         NEW
       │
       ▼
Compatibility ExecutableStep       NEW
       │
       ▼
Existing v1.0 Chat/RAG Orchestration
       │
       ├─ RetrievalPackageId        KEEP
       ├─ CX GenerationId           KEEP
       ├─ CX JobId                  KEEP
       ├─ GeneratedResponseId       KEEP
       └─ ArtifactId                KEEP
       │
       ▼
AgentResult                        NEW
       │
       ▼
ResultDelivery foundation          NEW
       │
       ├─ ACK only if conformant publication path exists
       └─ otherwise remain non-terminal for canonical AgentExecution
```

---

# 11. Agent Registry Requirements

## P4-REG-001

P4 SHALL implement persistence equivalent to the Frozen `001_ae_agent_registry.sql`.

## P4-REG-002

The canonical key SHALL be:

```text
(tenant_id, agent_id)
```

## P4-REG-003

Supported `agent_type` values SHALL be:

```text
IA | CA | PA | EA
```

## P4-REG-004

Supported status values SHALL be:

```text
ACTIVE | SUSPENDED | RETIRED
```

## P4-REG-005

P4 runtime admission SHALL execute only `ACTIVE` IA identities.

## P4-REG-006

P4 SHALL preserve the Frozen PA invariant in the schema even though PA execution is out of scope:

```text
PA requires project_id
at most one ACTIVE PA per (tenant_id, project_id)
```

## P4-REG-007

Registry writes SHALL support optimistic status transition by `expected_version`.

## P4-REG-008

P4 MUST NOT move Agent Registry ownership to OA, AG, WC, or CX.

---

# 12. ExecutionTrigger Requirements

## P4-TRG-001

P4 runtime path SHALL support only:

```text
source_type = PROMPT
agent_type  = IA
```

## P4-TRG-002

P4 SHALL use the Frozen ExecutionTrigger field set.

## P4-TRG-003

For the v1.0 compatibility path:

```text
source_ref = legacy InteractionId
```

is the canonical P4 mapping.

## P4-TRG-004

`trigger_id` SHALL be stable for one admitted prompt interaction.

The implementation MAY use deterministic derivation or persisted generation, but duplicate admission of the same source trigger MUST resolve to the same AgentExecution.

## P4-TRG-005

For PROMPT:

- `work_item_ref`
- `claim_ref`
- `claim_generation`
- `assignment_ref`

SHALL be absent/null.

## P4-TRG-006

P4 MUST reject or bypass runtime admission according to rollout mode if:

- IA AgentIdentity is unavailable/inactive
- trusted project_id is unavailable
- tenant context is unavailable
- correlation identity is invalid

## P4-TRG-007

P4 MUST NOT implement `CLAIMED_WORKITEM` runtime behavior.

The schema MAY be retained unchanged for future phases.

---

# 13. AgentExecution Requirements

## P4-EXE-001

P4 SHALL introduce a new persistent AgentExecution aggregate in the AE bounded context.

## P4-EXE-002

AgentExecution SHALL be keyed by:

```text
(tenant_id, agent_execution_id)
```

## P4-EXE-003

AgentExecution SHALL reference, without replacing:

- `agent_id`
- `agent_type`
- `trigger_id`
- `source_type`
- `source_ref`
- `project_id`
- `workspace_id` when available
- legacy `interaction_id` for the P4 compatibility path
- `correlation_id`
- optional `causation_id`

## P4-EXE-004

P4 SHALL enforce idempotent trigger admission.

At most one active/logical AgentExecution SHALL exist for one:

```text
tenant_id + trigger identity
```

## P4-EXE-005

The exact AgentExecution semantic `state` and `phase` vocabulary SHALL be extracted from the Frozen Agent v2.1 AgentExecution State Machine before implementation.

This SRS does not create a new competing enum.

## P4-EXE-006

AgentExecution state transitions SHALL be validated centrally in the Agent Runtime service/domain layer.

Route handlers MUST NOT mutate state ad hoc.

## P4-EXE-007

AgentExecution SHALL use optimistic versioning or equivalent atomic compare-and-set semantics for concurrent state transition safety.

## P4-EXE-008

Legacy ChatInteraction state SHALL remain a separate projection/state machine.

A Chat status transition MUST NOT implicitly mutate AgentExecution without the runtime transition service.

## P4-EXE-009

P4 SHALL retain a reference to the legacy Interaction rather than copying raw prompt or generated content into AgentExecution.

## P4-EXE-010

P4 SHALL allow future 1:N RuntimeJob relationships.

AgentExecution MUST NOT embed one permanent runtime-job slot.

---

# 14. P4 Physical AgentExecution Persistence Profile

This section is a **P4 implementation decision**, not a Frozen semantic amendment.

The physical schema SHOULD minimally support:

```text
tenant_id
agent_execution_id
agent_id
agent_type
trigger_id
source_type
source_ref
project_id

workspace_id                    nullable
legacy_interaction_id           nullable

state
phase                           nullable
version

result_id                       nullable

correlation_id
causation_id                    nullable

created_at
updated_at
```

Recommended constraints:

- primary key `(tenant_id, agent_execution_id)`
- unique `(tenant_id, trigger_id)`
- unique `(tenant_id, legacy_interaction_id)` where not null for the P4 one-prompt/one-execution compatibility mapping
- `agent_type = IA` for executions admitted by P4 PROMPT path
- no DB CHECK that narrows the Frozen AgentExecution state vocabulary unless the exact vocabulary has been extracted and confirmed

Cross-service foreign keys SHALL NOT be introduced.

Same-service reference constraints MAY be used only if they do not impair rollback/transition compatibility.

---

# 15. RuntimeJob Requirements

## P4-JOB-001

P4 SHALL implement the Frozen RuntimeJob v2.1 contract.

## P4-JOB-002

The runtime job table SHALL be `ae_runtime_job` as defined by the Frozen SQL.

## P4-JOB-003

P4 SHALL implement `ae_runtime_job_attempt`.

## P4-JOB-004

The Frozen RuntimeJob state vocabulary SHALL be:

```text
QUEUED
RUNNING
DONE
FAILED
CANCELLED
DEAD_LETTER
```

## P4-JOB-005

P4 SHALL preserve the Frozen RuntimeJob job-type vocabulary:

```text
START_EXECUTION
CONTINUE_EXECUTION
RESUME_EXECUTION
RETRY_EXECUTION
RECONCILE_EXECUTION
PUBLISH_RESULT
RECONCILE_PUBLICATION
```

P4 behavior SHALL initially implement only the subset explicitly required by this SRS.

## P4-JOB-006

Minimum P4 implemented job behavior SHALL include:

```text
START_EXECUTION
```

## P4-JOB-007

`RuntimeJob.execution_id` SHALL carry `AgentExecutionId`.

## P4-JOB-008

`RuntimeJobId` MUST remain distinct from existing service `service_jobs` IDs and CX JobId.

## P4-JOB-009

P4 MAY reuse existing shared JobQueue algorithms/patterns, but canonical Agent Runtime jobs SHALL persist to `ae_runtime_job`.

## P4-JOB-010

RuntimeJob deduplication SHALL use:

```text
UNIQUE (tenant_id, dedup_key)
```

as defined by the Frozen SQL.

## P4-JOB-011

A START_EXECUTION dedup key SHALL be stable for one AgentExecution.

The exact string format is an implementation detail and SHALL be documented in the implementation plan/tests.

## P4-JOB-012

RuntimeJob attempt numbering SHALL respect:

- job aggregate `attempt_no` minimum 0
- attempt records `attempt_no` minimum 1

## P4-JOB-013

RUNNING jobs SHALL require:

- lease_owner
- lease_token
- lease_until

## P4-JOB-014

Job completion SHALL validate the current lease token.

A stale worker MUST NOT complete a job after lease ownership is lost.

## P4-JOB-015

P4 SHALL preserve the distinction between:

```text
RuntimeJob retry
and
new user logical AgentExecution
```

Technical retry MUST NOT automatically create a new AgentExecution.

---

# 16. P4 Runtime Execution Mode

To preserve v1.0 public behavior, P4 SHOULD initially use an **inline compatibility runner**.

Canonical P4 pattern:

```text
HTTP Chat request
→ persist/admit AgentExecution
→ enqueue START_EXECUTION RuntimeJob
→ same process claims that exact job through RuntimeJobQueue
→ create RuntimeJobAttempt
→ execute CompatibilityStep
→ finish attempt/job
→ return legacy-compatible HTTP result
```

The implementation SHALL keep the queue/repository boundary real even if the first runner is inline.

A future process worker SHALL be able to consume the same RuntimeJob contract without changing AgentExecution semantics.

---

# 17. Compatibility ExecutableStep Requirements

## P4-STEP-001

P4 SHALL introduce a distinct `ExecutableStepId`.

## P4-STEP-002

The P4 compatibility step SHALL wrap the existing v1.0 Chat/RAG orchestration.

It MUST NOT duplicate or fork:

- CX retrieval logic
- CX generation logic
- MO provider logic
- citation-quality logic
- GeneratedResponse storage logic
- artifact lifecycle logic

## P4-STEP-003

The compatibility step SHALL invoke existing service/domain functions through an adapter boundary.

It SHOULD NOT call the HTTP route recursively.

## P4-STEP-004

The compatibility step SHALL preserve existing IDs returned/created by the v1.0 path.

## P4-STEP-005

The compatibility step SHALL produce a structured step outcome containing references such as:

- legacy InteractionId
- RetrievalPackageId/hash when present
- CX GenerationId when present
- CX JobId when present
- GeneratedResponseId when present
- Artifact refs
- quality/warning/error summary
- correlation metadata

It SHALL NOT copy raw user prompt or raw generated response into the step record merely for convenience.

## P4-STEP-006

The compatibility step MUST NOT become an NSL Skill step.

NSL integration begins in P5.

## P4-STEP-007

The exact Frozen `ExecutableStep` semantic vocabulary SHALL be read from the Agent Frozen set before the physical persistence/domain enum is finalized.

---

# 18. P4 Physical ExecutableStep Persistence Profile

This is a P4 implementation decision.

A minimal persisted compatibility step SHOULD support:

```text
tenant_id
executable_step_id
agent_execution_id

step_kind = P4 compatibility discriminator
state

legacy_interaction_id
retrieval_package_ref/hash       nullable
cx_generation_id                 nullable
cx_job_id                        nullable
generated_response_id            nullable

result_ref                       nullable
error_ref                        nullable

correlation_id
causation_id                     nullable

created_at
updated_at
```

The P4 compatibility discriminator SHALL be treated as transition implementation metadata, not as a new Frozen business taxonomy.

---

# 19. Existing Chat/RAG Compatibility Requirements

## P4-COMP-001

Existing Chat API routes SHALL remain available and backward compatible.

## P4-COMP-002

P4 SHALL NOT require clients to send AgentExecutionId.

## P4-COMP-003

P4 SHALL NOT require clients to send AgentId as an untrusted browser field.

## P4-COMP-004

Existing InteractionId generation/idempotency SHALL remain unchanged.

## P4-COMP-005

Existing Workspace ownership checks SHALL remain unchanged.

## P4-COMP-006

Existing CX retrieval and generation calls SHALL remain semantically unchanged in P4.

## P4-COMP-007

Existing async Chat refresh/cancel/retry/recovery semantics SHALL continue to work.

## P4-COMP-008

Existing GeneratedResponse content integrity and private storage SHALL remain unchanged.

## P4-COMP-009

Existing Artifact linkage SHALL remain unchanged.

## P4-COMP-010

P4 wrapper failures in shadow mode MUST NOT break a valid legacy Chat/RAG request.

## P4-COMP-011

P4 MUST emit a safe diagnostic when wrapper admission or shadow persistence fails.

Raw prompt, raw generated content, credentials, provider paths, and DB URLs MUST NOT appear in that diagnostic.

---

# 20. AgentResult Requirements

## P4-RES-001

P4 SHALL implement the Frozen `AgentResult v2.1` schema as the target result contract.

## P4-RES-002

P4 SHALL persist AgentResult to the Frozen `ae_agent_result` table shape or a byte/field-compatible implementation of that normative contract.

## P4-RES-003

For P4 IA execution:

```text
agent_type = IA
```

and WC claim-lineage fields SHALL remain null/not-applicable.

## P4-RES-004

AgentResult SHALL contain references to existing v1.0 objects.

It SHALL NOT replace them.

## P4-RES-005

`structured_result` SHOULD contain a safe semantic projection.

It SHOULD reference rather than duplicate private response content.

## P4-RES-006

`artifact_refs` SHALL be populated from stable existing Artifact identities when artifacts exist.

## P4-RES-007

`evidence_refs` SHOULD include stable retrieval/evidence references when grounded retrieval occurred.

## P4-RES-008

`citation_refs` MAY include stable citation/evidence references when available.

## P4-RES-009

`provenance` SHALL include sufficient reference lineage to reconstruct:

```text
AgentExecution
→ ExecutableStep
→ Interaction
→ CX Generation/Job
→ GeneratedResponse/Artifact
```

without embedding raw private content.

## P4-RES-010

`result_hash` SHALL follow the hashing semantics specified by the Frozen Agent result design if specified there.

If the Frozen DOCX does not define a canonical hashing algorithm, the implementation SHALL record the proposed canonical hash projection in the P4 Issue Register before coding and SHALL use stable canonical JSON hashing.

It MUST NOT hash raw private content merely because the content exists.

---

# 21. Legacy → AgentResult Compatibility Mapping

The following mapping is a P4 transition decision.

## P4-RES-MAP-01

Legacy ChatInteraction `PENDING` SHALL NOT create a terminal AgentResult.

## P4-RES-MAP-02

Legacy ChatInteraction `COMPLETED` SHOULD map to:

```text
AgentResult.status = SUCCEEDED
```

unless quality/citation state indicates unresolved attention.

## P4-RES-MAP-03

If legacy Chat completes but carries unresolved quality/citation attention that prevents a clean success classification, P4 SHOULD map:

```text
AgentResult.status = PARTIAL
```

and preserve warning/evidence references.

## P4-RES-MAP-04

Legacy `NO_ANSWER` SHALL map to:

```text
AgentResult.status = BLOCKED
```

with a safe reason/warning indicating evidence insufficiency/no-answer semantics.

It SHALL NOT be converted into a fabricated answer.

## P4-RES-MAP-05

Explicit legacy async cancellation SHALL map to:

```text
AgentResult.status = CANCELLED
```

when the cancellation terminal state is authoritative.

## P4-RES-MAP-06

Other legacy terminal technical failure SHALL map to:

```text
AgentResult.status = FAILED
```

with safe error references, not raw exception data.

---

# 22. ResultDelivery Foundation

## P4-DEL-001

P4 SHALL recognize the Frozen ResultDelivery contract from Batch08.

## P4-DEL-002

P4 SHALL support creation of a required `WORKSPACE_RESULT` delivery record for IA compatibility results when the implementation has enough authoritative data to do so.

## P4-DEL-003

P4 SHALL NOT create required WC WorkResult delivery.

That is P6+ background-agent scope.

## P4-DEL-004

P4 SHALL NOT implement optional Email/Messenger/WA/Metrics/Analytics/Dashboard fan-out.

## P4-DEL-005

P4 MUST NOT mark a ResultDelivery `ACKNOWLEDGED` without the required Frozen publication preflight semantics.

## P4-DEL-006

If AS_OF_NOW OA/scope/classification/visibility preflight is not yet conformantly implemented, ResultDelivery SHALL remain in an appropriate non-acknowledged state.

## P4-DEL-007

Canonical AgentExecution terminal success MUST remain blocked until required delivery acknowledgement requirements are satisfied.

## P4-DEL-008

Legacy Chat completion remains independent for backward compatibility and MUST NOT be used as evidence that canonical ResultDelivery has been acknowledged.

---

# 23. Rollout / Feature Flag Requirements

P4 SHALL support controlled rollout.

Recommended runtime mode:

```text
disabled
shadow
required
```

The exact environment variable name is an implementation detail; the implementation plan SHALL document it.

## P4-ROLL-001 — disabled

- execute only existing v1.0 path
- no canonical wrapper required for request success

## P4-ROLL-002 — shadow

- attempt Frozen-conformant Agent Runtime admission
- if admission succeeds, create/trace canonical runtime wrapper
- if canonical admission data is unavailable, preserve legacy request behavior
- emit safe diagnostic/metric
- wrapper failure MUST NOT corrupt legacy state

## P4-ROLL-003 — required

- request must satisfy canonical P4 runtime admission
- missing/invalid tenant, IA AgentIdentity, project context, or required runtime state fails deterministically
- no synthetic project/agent values

## P4-ROLL-004

Default rollout mode for transition deployment SHOULD be `disabled` until P4 acceptance passes.

## P4-ROLL-005

Tests SHALL cover all three rollout modes.

---

# 24. Trusted Runtime Admission Context

P4 SHOULD define an internal interface similar to:

```text
P4RuntimeAdmissionContext
├─ tenant_id
├─ agent_id
├─ agent_type = IA
├─ project_id
├─ principal_ref
├─ workspace_id
├─ interaction_id
├─ correlation_id
└─ causation_id?
```

Requirements:

## P4-ADM-001

The context SHALL be built from server-side authenticated/validated state.

## P4-ADM-002

Browser payload fields SHALL NOT override tenant/agent/project authority.

## P4-ADM-003

P4 SHALL support dependency injection of the admission resolver for deterministic tests.

## P4-ADM-004

P4 SHALL seed active IA AgentIdentity and trusted project context explicitly in tests.

## P4-ADM-005

P4 SHALL NOT introduce an implicit "default project" merely to satisfy the ExecutionTrigger schema.

---

# 25. Persistence and Migration Requirements

## P4-PER-001

All P4 database changes SHALL be additive.

## P4-PER-002

Existing v1.0 tables SHALL NOT be renamed or destructively repurposed.

## P4-PER-003

P4 SHALL add the Frozen Agent Registry table exactly/equivalently.

## P4-PER-004

P4 SHALL add the Frozen RuntimeJob and RuntimeJobAttempt tables exactly/equivalently.

## P4-PER-005

P4 SHALL add AgentResult persistence compatible with Batch08.

## P4-PER-006

P4 SHALL add ResultDelivery persistence only as required by this SRS and SHALL preserve the Frozen schema shape.

## P4-PER-007

P4 SHALL add a dedicated AgentExecution persistence model.

## P4-PER-008

P4 SHOULD add dedicated compatibility ExecutableStep persistence rather than embedding step history into ChatInteraction JSON.

## P4-PER-009

P4 SHALL NOT add cross-service database foreign keys.

## P4-PER-010

P4 migration scripts SHALL be idempotent under the repository's migration runner conventions.

## P4-PER-011

SQLite regression compatibility SHALL be maintained where the v1.0 repository uses SQLite repository tests.

PostgreSQL DDL remains canonical.

## P4-PER-012

Protected PostgreSQL smoke SHALL reset/clean only test rows created by the smoke and SHALL use test-profile guardrails.

---

# 26. RuntimeJob Claim / Lease Requirements

## P4-LEASE-001

RuntimeJob claim SHALL be atomic.

## P4-LEASE-002

Only `QUEUED` and runnable jobs may be claimed.

## P4-LEASE-003

Claim SHALL assign:

- lease_owner
- lease_token
- lease_until
- RUNNING state

atomically.

## P4-LEASE-004

A RuntimeJobAttempt SHALL be created per claim attempt.

## P4-LEASE-005

Completion/failure SHALL require the current lease token.

## P4-LEASE-006

Lease expiry handling SHALL not silently execute the same job twice.

P4 MAY defer automatic lease-reconciliation job orchestration, but tests SHALL prove stale completion is rejected.

## P4-LEASE-007

P4 SHALL distinguish RuntimeJob lease from all future:

- WC Work claim
- NSL write idempotency
- business operation identity

---

# 27. Error and Retry Requirements

## P4-ERR-001

P4 SHALL use deterministic stable error codes.

## P4-ERR-002

Errors SHALL identify whether failure occurred in:

- runtime admission
- AgentExecution persistence
- RuntimeJob enqueue/claim
- compatibility step
- legacy Chat/RAG
- AgentResult persistence
- ResultDelivery foundation

without exposing secrets/private content.

## P4-ERR-003

Technical RuntimeJob retry SHALL remain within the same AgentExecution.

## P4-ERR-004

User-requested semantic retry SHALL preserve the v1.0 child Interaction behavior until a later phase explicitly redefines its AgentExecution semantics.

P4 SHALL NOT silently merge user semantic retry with technical RuntimeJob retry.

## P4-ERR-005

P4 SHALL preserve existing cancel/race reconciliation behavior of the nested legacy Chat/CX path.

## P4-ERR-006

P4 does not implement UNKNOWN_COMMIT_STATE behavior because business WRITE is out of scope.

The RuntimeJob schema may contain future reconciliation job types without implementing them.

---

# 28. Observability and Audit Requirements

## P4-OBS-001

Every canonical P4 runtime record SHALL carry:

- tenant_id
- correlation_id
- relevant execution identity

## P4-OBS-002

Safe observability SHOULD trace:

```text
InteractionId
→ AgentExecutionId
→ RuntimeJobId
→ ExecutableStepId
→ CX GenerationId / CX JobId
→ GeneratedResponseId
→ AgentResultId
```

when each identity exists.

## P4-OBS-003

Logs/events MUST NOT include:

- raw prompt
- raw generated response
- credentials
- provider URL/API key
- DB URL
- object-store secret
- raw private evidence

## P4-OBS-004

P4 wrapper observability failure SHOULD NOT fail a valid legacy request in `shadow` mode.

## P4-OBS-005

P4 SHOULD emit metrics for:

- runtime admissions attempted
- admitted
- bypassed
- failed
- duplicate trigger reuse
- RuntimeJob enqueued/claimed/completed/failed
- AgentResult persisted
- delivery pending/ack blocked

---

# 29. Security Requirements

## P4-SEC-001

Tenant context SHALL be explicit.

P4 MUST NOT derive TenantId from OrgScope or ProjectScope.

## P4-SEC-002

IA AgentIdentity SHALL be resolved from the AE Agent Registry.

## P4-SEC-003

Agent status other than ACTIVE SHALL not be admitted.

## P4-SEC-004

Project context SHALL be trusted/validated.

## P4-SEC-005

P4 SHALL preserve existing v1.0 owner-scope protections.

## P4-SEC-006

P4 SHALL not weaken OA/service-token boundaries.

## P4-SEC-007

No new direct provider endpoint access may be introduced in AE.

## P4-SEC-008

P4 SHALL not copy full AgentContext into future NSL-shaped structures.

---

# 30. API Compatibility Requirements

## P4-API-001

No breaking change is permitted to existing v1.0 public Chat request/response contracts in P4.

## P4-API-002

No client-supplied AgentExecutionId is required.

## P4-API-003

No client-supplied RuntimeJobId is required.

## P4-API-004

No client-supplied AgentResultId is required.

## P4-API-005

P4 MAY add internal/admin read projections for debugging, but they SHALL:

- be authenticated
- be owner/operator scoped as appropriate
- expose no raw private content
- not become new business SoR

## P4-API-006

If no new public API is required, P4 SHOULD prefer internal service interfaces and tests rather than expanding the public surface.

---

# 31. Refactoring-First Requirements

## P4-REF-001

Before adding runtime behavior, Codex SHALL inspect whether existing `chat.py` orchestration can be extracted behind a reusable service/adapter boundary.

## P4-REF-002

If the current route handler owns too much orchestration logic to be safely called from RuntimeJob execution, a behavior-preserving refactor SHALL precede feature implementation.

## P4-REF-003

Large cross-cutting refactoring SHALL be committed separately from new runtime semantics where practical.

## P4-REF-004

Existing regression SHALL pass after each refactoring slice before feature work continues.

## P4-REF-005

P4 SHOULD avoid placing all new runtime logic into `chat.py`.

A cohesive internal runtime package/module boundary is preferred.

---

# 32. Recommended Logical Code Boundaries

Exact filenames are not normative; Codex SHALL propose them before implementation.

Recommended responsibilities:

```text
agent_runtime/
  models / contracts
  registry
  admission
  execution repository/service
  runtime job queue/repository
  compatibility chat step
  result mapper/repository
  delivery foundation
  observability
```

Existing v1.0 modules remain the owners of:

```text
chat interaction
workspace
retrieval facade
CX generation client
generated response storage/lineage
artifact lifecycle
```

---

# 33. P4 Execution Sequence

## 33.1 Admission

```text
existing authenticated Chat intake
→ Workspace/Interaction validation
→ resolve P4 runtime admission context
→ validate active IA + project
→ build PROMPT ExecutionTrigger
→ create_or_get AgentExecution
```

## 33.2 Runtime Job

```text
AgentExecution
→ enqueue_unique START_EXECUTION
→ claim with lease
→ RuntimeJobAttempt RUNNING
```

## 33.3 Compatibility Step

```text
START_EXECUTION
→ create/load Compatibility ExecutableStep
→ invoke existing Chat/RAG orchestration adapter
→ preserve legacy identifiers/results
```

## 33.4 Result Foundation

```text
legacy terminal outcome
→ map to AgentResult
→ persist immutable AgentResult
→ create required ResultDelivery foundation if applicable
```

## 33.5 Completion

```text
If Frozen required delivery ACK conditions are conformantly satisfied:
    AgentExecution may enter Frozen SUCCEEDED terminal state
Else:
    AgentExecution stays in the correct Frozen pre-terminal/finalization state
```

Legacy Chat API completion remains independent for transition compatibility.

---

# 34. Idempotency Requirements

## P4-IDEMP-001

Duplicate PROMPT trigger admission SHALL not create duplicate AgentExecutions.

## P4-IDEMP-002

Duplicate START_EXECUTION enqueue SHALL not create duplicate RuntimeJobs for the same dedup key.

## P4-IDEMP-003

Duplicate AgentResult creation for the same semantic execution outcome SHALL either:

- return the exact existing result
- or fail deterministically on semantic mismatch

It MUST NOT create silent divergent duplicate results.

## P4-IDEMP-004

Existing CX generation idempotency SHALL remain unchanged.

## P4-IDEMP-005

P4 idempotency SHALL NOT be described as NSL WRITE idempotency.

---

# 35. AgentResult Immutability Requirements

## P4-IMM-001

Once persisted, semantic AgentResult content SHALL be immutable.

## P4-IMM-002

Publication/delivery state SHALL live in ResultDelivery, not by mutating AgentResult.

## P4-IMM-003

A later publication retry SHALL not mutate or regenerate the existing business/generated result.

## P4-IMM-004

P4 SHALL preserve the Frozen separation:

```text
AgentResult
!= ResultDelivery
```

---

# 36. Data Privacy Requirements

## P4-DATA-001

AgentExecution SHOULD store references/hashes/previews, not raw prompt.

## P4-DATA-002

RuntimeJob payload SHALL be minimal and safe.

## P4-DATA-003

Compatibility step persistence SHALL not duplicate raw generated response.

## P4-DATA-004

AgentResult structured_result SHALL not duplicate large private payloads when stable references already exist.

## P4-DATA-005

Existing private GeneratedResponse storage remains authoritative for generated content.

---

# 37. Test Strategy

P4 testing SHALL follow the repository's existing Slice / Checkpoint / Full Gate discipline.

## 37.1 Unit Tests

Required areas:

- AgentIdentity validation
- AgentRegistry create/get/status transition
- PROMPT ExecutionTrigger validation
- runtime admission
- duplicate trigger idempotency
- AgentExecution transition validation
- RuntimeJob validation
- RuntimeJob dedup
- lease claim
- stale lease rejection
- RuntimeJobAttempt
- compatibility step mapping
- AgentResult status mapping
- AgentResult immutability/hash
- ResultDelivery completion gate
- rollout modes

## 37.2 Boundary / Robustness / Worst-Case Cases

At minimum:

- empty tenant
- inactive IA
- missing project_id
- duplicate trigger concurrent calls
- same trigger with conflicting semantic source
- duplicate RuntimeJob dedup key
- lease expiry
- stale lease completion
- compatibility adapter exception
- legacy NO_ANSWER
- legacy cancellation
- legacy technical failure
- GeneratedResponse integrity failure
- duplicate AgentResult same semantics
- duplicate AgentResult different semantics
- missing ResultDelivery preflight
- attempted SUCCEEDED without delivery ACK
- shadow wrapper DB failure while legacy path succeeds

## 37.3 Repository / DB Tests

- SQLite repository regression where supported
- PostgreSQL migration smoke
- PostgreSQL AgentRegistry smoke
- PostgreSQL AgentExecution/RuntimeJob smoke
- PostgreSQL AgentResult/ResultDelivery smoke
- test database reset/cleanup before each protected DB smoke

## 37.4 Contract Tests

Generated/runtime records SHALL be validated against the Frozen JSON schemas where those schemas exist.

At minimum:

- AgentIdentity
- ExecutionTrigger
- RuntimeJob
- RuntimeJobAttempt
- AgentResult
- ResultDelivery

The implementation SHOULD use a dev/test-only schema validator or equivalent exact contract tests.

## 37.5 Existing Regression

P4 SHALL not pass if the existing v1.0 owning-service regression fails.

## 37.6 Playwright

No new user-facing behavior is required, but existing authenticated Chat/RAG golden journey and relevant browser regressions SHALL continue to pass.

---

# 38. Coverage Gates

Repository thresholds remain authoritative.

For changed-source / checkpoint quality:

```text
Statement coverage >= 95%
Branch coverage    >= 94%
```

P4 SHALL investigate unexplained coverage regression even if numeric minimums pass.

---

# 39. P4 Implementation Slices

Recommended sequence:

## P4-S1 — Refactor-only Compatibility Boundary
- extract reusable legacy Chat/RAG orchestration service/adapter
- no new runtime semantics
- full relevant regression

## P4-S2 — Agent Registry Foundation
- migration
- repository/service
- contract tests
- active IA admission primitive

## P4-S3 — AgentExecution Foundation
- physical schema
- repository
- exact Frozen state/phase extraction
- transition service
- idempotent trigger mapping

## P4-S4 — RuntimeJob Foundation
- Frozen SQL/schema
- queue/repository
- lease/attempt
- inline runner

## P4-S5 — PROMPT Runtime Admission
- build ExecutionTrigger
- shadow/required mode
- project/agent trusted context
- duplicate admission

## P4-S6 — Compatibility ExecutableStep
- wrap existing v1 Chat/RAG path
- end-to-end IDs
- no semantic rewrite of CX/MO

## P4-S7 — AgentResult Foundation
- Frozen AgentResult contract/table
- legacy terminal mapping
- immutable result

## P4-S8 — ResultDelivery Safety Foundation
- Frozen delivery table/contract
- no fake ACK
- success gate protection

## P4-S9 — Observability / Read Model / Diagnostics
- trace chain
- safe metrics/events
- optional internal read projection

## P4-S10 — P4 Closure
- full regression
- PostgreSQL protected smoke
- Playwright regression
- contract validation
- exit-gate report

---

# 40. Required Codex Pre-Implementation Plan

Before changing code, Codex SHALL submit a plan containing:

1. exact Frozen AgentExecution state/phase vocabulary extracted from Agent Doc 01
2. current v1.0 route/service call graph for Chat creation
3. exact refactor required to make legacy orchestration callable from RuntimeJob
4. proposed new files/modules
5. proposed migrations
6. AgentExecution physical schema
7. ExecutableStep physical schema
8. runtime rollout flag/modes
9. trusted IA/project admission source
10. AgentResult hash strategy and Frozen source reference
11. ResultDelivery P4 strategy
12. test mapping by Requirement ID
13. rollback plan
14. known conflicts/issues

Codex MUST NOT begin feature implementation before this plan is reviewed.

---

# 41. Known P4 Issue Register Seed

These issues SHALL be copied into the P4 Issue Register before implementation.

## P4-ISSUE-001 — AgentExecution machine-readable schema absent from inspected normative directory

Action:
- extract exact semantic vocabulary from Frozen Agent Doc 01
- use this SRS physical profile only as implementation guidance
- do not create competing semantics

## P4-ISSUE-002 — Trusted IA AgentIdentity provisioning

Action:
- define how an authenticated v1.0 user resolves to an ACTIVE IA AgentIdentity
- do not trust browser-provided agent_id
- do not invent policy silently

## P4-ISSUE-003 — PROMPT requires project_id

Action:
- define trusted project context source
- preserve legacy behavior in shadow mode when unavailable
- strict mode fails deterministically
- no fake/default project unless separately approved by architecture decision

## P4-ISSUE-004 — Full ResultDelivery preflight depends on later OA/authority integration

Action:
- implement foundation without fake authorization evidence
- block canonical AgentExecution SUCCEEDED unless ACK is genuinely conformant

---

# 42. Acceptance Criteria

P4 is accepted only when all mandatory criteria pass.

## P4-AC-01 — v1.0 Compatibility

With runtime mode `disabled`:

- existing Chat/RAG behavior matches v1.0 baseline
- existing owning-service regression passes

## P4-AC-02 — Runtime Admission

With test-seeded trusted IA/project context:

```text
PROMPT
→ one ExecutionTrigger
→ one AgentExecution
```

Duplicate submission returns/reuses the same logical AgentExecution.

## P4-AC-03 — Identity Separation

Tests prove:

```text
InteractionId       != AgentExecutionId
CX JobId            != RuntimeJobId
CX GenerationId     != ExecutableStepId
GeneratedResponseId != AgentResultId
```

## P4-AC-04 — RuntimeJob

At least one START_EXECUTION RuntimeJob is:

- persisted
- claimed with lease
- recorded as an attempt
- executed
- completed using valid lease token

## P4-AC-05 — Compatibility Step

Existing v1.0 Chat/RAG path executes through the compatibility adapter without duplicating CX/MO business logic.

## P4-AC-06 — AgentResult

Terminal legacy outcome creates exactly one immutable AgentResult with safe lineage references.

## P4-AC-07 — Completion Safety

Tests prove AgentExecution cannot become terminal SUCCEEDED when required ResultDelivery is not ACKNOWLEDGED.

## P4-AC-08 — No Scope Leakage

No implementation of:

- WC Claim execution
- NSL
- WRITE
- Approval
- EOS
- WA
- Schedule

is introduced.

## P4-AC-09 — Database

All P4 migrations apply cleanly to isolated test PostgreSQL.

Existing migrations remain valid.

## P4-AC-10 — Quality

- required unit/contract/smoke tests pass
- existing regression passes
- coverage thresholds pass
- relevant Playwright regression passes

## P4-AC-11 — Frozen Integrity

No file under:

```text
docs/frozen/v2.1/
```

except the already-approved `README_FROZEN_BASELINE.md` guide is modified by P4 implementation.

Frozen hashes/manifests remain unchanged.

---

# 43. P4 Exit Gate

The P4 exit gate is:

```text
Existing v1.0 Chat/RAG behavior = regression PASS

AND

PROMPT
→ AgentExecutionId
→ RuntimeJobId
→ ExecutableStepId
→ legacy Interaction/CX path
→ AgentResultId

is traceable end-to-end

AND

canonical completion rules are not falsified

AND

P5+ scope is not implemented
```

If full ResultDelivery/OA preflight is not yet implemented, P4 may close with the canonical execution in the Frozen pre-terminal/finalization state, provided:

- the AgentResult is durable
- required delivery remains explicitly non-ACKNOWLEDGED
- no false `SUCCEEDED` is recorded
- legacy Chat UX remains backward compatible
- the remaining publication dependency is recorded for the later phase

---

# 44. Definition of Done

P4 is DONE when:

- all P4 mandatory requirements are implemented
- all P4 acceptance criteria pass
- P4 Issue Register has no open P0/P1 implementation blocker
- implementation plan and actual files/migrations match
- no Frozen semantic contract was silently altered
- the branch is ready for P5 NSL v0.2 READ integration planning

---

# 45. Next Phase Boundary

After P4 closure, P5 may begin:

```text
AgentExecution
→ ExecutableStep
→ Skill Artifact Gateway
→ VerifiedSkillArtifact
→ NSL v0.2 READ
→ NSL Result Summary
→ StepResult
→ AgentResult
```

P5 SHALL reuse the P4 identities rather than retrofitting them.

P4 therefore MUST finish with identity and runtime boundaries stable enough for NSL integration without renaming core objects.

---

# Appendix A — P4 Core Trace Chain

```text
TenantId
  │
  ├─ AgentId (IA)
  │
  ├─ WorkspaceId
  │
  └─ ProjectId
        │
        ▼
InteractionId                         legacy v1
        │
        ▼
ExecutionTriggerId                    new P4
        │
        ▼
AgentExecutionId                      new P4
        │
        ▼
RuntimeJobId                          new P4
        │
        ▼
ExecutableStepId                      new P4
        │
        ├─ RetrievalPackageId         legacy v1
        ├─ CX GenerationId            legacy v1
        ├─ CX JobId                   legacy v1
        ├─ GeneratedResponseId        legacy v1
        └─ ArtifactId                 legacy v1
        │
        ▼
AgentResultId                         new P4
        │
        ▼
ResultDeliveryId                      new foundation
```

---

# Appendix B — P4 Requirement Families

```text
P4-ID-*       Identity
P4-CONSTRAINT-* Transition constraints
P4-REG-*      Agent Registry
P4-TRG-*      ExecutionTrigger
P4-EXE-*      AgentExecution
P4-JOB-*      RuntimeJob
P4-LEASE-*    Lease/attempt
P4-STEP-*     Compatibility step
P4-COMP-*     v1 compatibility
P4-RES-*      AgentResult
P4-DEL-*      ResultDelivery
P4-ROLL-*     Rollout
P4-ADM-*      Trusted admission
P4-PER-*      Persistence
P4-ERR-*      Error/retry
P4-OBS-*      Observability
P4-SEC-*      Security
P4-API-*      API
P4-REF-*      Refactoring
P4-IDEMP-*    Idempotency
P4-IMM-*      Result immutability
P4-DATA-*     Privacy
P4-AC-*       Acceptance
```

---

# Appendix C — Codex Implementation Rule

> Read Frozen first.  
> Read Transition second.  
> Read this SRS third.  
> Inspect source fourth.  
> Produce implementation plan fifth.  
> Refactor before feature work when necessary.  
> Implement in small slices.  
> Run regression after every source change.  
> Do not cross the P4 boundary.
