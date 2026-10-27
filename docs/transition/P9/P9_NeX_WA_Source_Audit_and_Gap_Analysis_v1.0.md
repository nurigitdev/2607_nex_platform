# P9 — NeX-WA (Work Asset)
# Source Audit and Gap Analysis v1.0

**Status:** SOURCE-BACKED AUDIT / PRE-CONTRACT-CLOSURE
**Phase:** P9 — NeX-WA / Work Asset Foundation
**Platform:** NeX Platform v2.1
**Predecessor:** `P9_NeX_WA_Pre_Architecture_Decision_v1.2.md`
**P8 Final Handoff:** `P8_Final_AsBuilt_Baseline_and_P9_Handoff_v1.2.md`
**Repository:** `nurigitdev/2607_nex_platform`
**Branch:** `transition/p4-agent-runtime-foundation`
**Audited HEAD:** `c3a1ea907387b67fe7a63407e4d668d13b1be8e7`
**Audited Tree:** `7df03a1ff280baefbda4e56b1ff0e0818ef0bde3`
**Date:** 2026-10-27
**Next:** P9 Contract Closure

---

# 1. Audit Purpose

This audit determines what NeX-WA Foundation can reuse from the completed P8
platform and what must actually be added in P9.

The audit is intentionally constrained by the approved P9 Pre-Architecture
Decision.

The goal is not to design a large new platform. The goal is to identify the
smallest source-backed implementation required for:

```text
authoritative work source
        ↓
approval-free background intake
        ↓
WA service-local JobQueue
        ↓
deterministic source verification
        ↓
WorkEvidence
        ↓
WorkAsset / WorkFact
        ↓
bounded contribution candidate
```

The audit distinguishes every material finding as one of:

```text
SOURCE-BACKED
REUSE
GAP
RECOMMENDATION
OPEN
DEFERRED
```

---

# 2. Executive Finding

The current P8 repository already contains most of the infrastructure required
for NeX-WA Foundation.

P9 does NOT need to build:

```text
a new scheduler
a new distributed message broker
a new Agent RuntimeJob system
a new Human identity system
a new Agent identity system
a new Project identity system
a new Worker framework
a new JobQueue abstraction
a new heartbeat abstraction
a new approval workflow
a new NSL execution path
```

P9 primarily needs to add:

```text
NeX-WA service ownership
WA persistence
WA evidence intake contract
WA source adapters/projections
WA evidence normalization
WA source/evidence idempotency
WA Human/Agent actor normalization
WA Project attribution validation
WA queries
later bounded contribution candidate calculation
```

The most important source-audit conclusion is:

> **P9 is primarily a new evidence domain, not a new execution platform.**

---

# 3. Repository Baseline

The audited repository state is:

```text
repository = nurigitdev/2607_nex_platform
branch     = transition/p4-agent-runtime-foundation
HEAD       = c3a1ea907387b67fe7a63407e4d668d13b1be8e7
tree       = 7df03a1ff280baefbda4e56b1ff0e0818ef0bde3
```

This HEAD is the merge of the P8-DEMO release-hardening PR into the transition
branch.

P8 is closed and P9 entry is authorized.

---

# 4. P8 Handoff Constraints

P8 Final As-Built v1.2 explicitly defines P9 as:

```text
NeX-WA / Work Asset
```

and explicitly states that P9 is not a scheduler.

P9 must preserve:

```text
tenant isolation
current authority
approval-domain separation
exactly-once semantics where applicable
reconciliation / verification boundaries
attachment / evidence lineage
Project membership
operation identity
model candidate vs authority separation
```

P9 receives no authority to directly mutate OA, AE, WC, EOS or NSL state.

**Finding:** SOURCE-BACKED / FROZEN CONSTRAINT

---

# 5. Current NeX-WA Implementation Inventory

The audited tree contains no current first-class NeX-WA implementation.

Missing:

```text
services/nex-wa/
database/nex-wa/
contracts/...nex_wa...
wa_work_asset
wa_work_evidence
wa_work_fact
wa_contribution_candidate
HumanEffortCandidate implementation
AgentEffortCandidate implementation
```

The only repository paths matching Work Asset / Human Effort concepts are
Frozen reference documents.

**Finding:** GAP

P9 therefore starts from a clean service/domain boundary.

---

# 6. Frozen Work Asset References Located

The repository contains:

```text
docs/frozen/v2.1/10_PLATFORM_v2.1/02_DETAILED_DESIGN/
23_NeX_Work_Asset_Human_Effort_and_Labor_Allocation_Design_v2.0.docx

docs/frozen/v2.1/10_PLATFORM_v2.1/04_LEGACY_REFERENCE_CONTRACTS/
23_NeX_Work_Asset_Human_Effort_and_Labor_Allocation_Implementation_Contracts_v2.0.zip
```

These files were inventoried as Frozen source references.

The repository connector exposed these as binary artifacts, not extracted text.
Therefore this Source Audit does **not** claim any internal requirement from
their contents that was not independently visible in current executable source.

**Finding:** OPEN / REQUIRES CONTRACT-CLOSURE RECONCILIATION

Before Contract Closure is frozen, those Frozen references should be
materialized and reconciled explicitly against:

```text
P9 PAD v1.2
current P8 As-Built source
this Source Audit
```

---

# 7. Shared JobQueue Foundation Already Exists

Current source:

```text
services/_shared/nex_runtime/jobs.py
```

already defines the shared general-service JobQueue abstraction.

It includes:

```text
common_job.v1
QUEUED
RUNNING
SUCCEEDED
FAILED
CANCELLED

JobQueue
InMemoryJobQueue
SqlAlchemyJobQueue

retry
dead letter
replay
idempotency
available_at
locked_by
locked_at
attempt_count
max_attempts
```

**Finding:** REUSE

P9 should reuse this shared JobQueue.

---

# 8. JobQueue Database Foundation Already Exists

Current services already use the common migration:

```text
0083_service_job_queue_foundation.sql
```

with service-local:

```text
service_jobs
```

The table includes:

```text
job_id
job_schema_version
job_type
status
trace_id
request_id
subject_type
subject_id
idempotency_key
attempt_count
max_attempts
retryable
links
payload
error
available_at
locked_at
locked_by
started_at
completed_at
created_at
updated_at
```

and:

```text
UNIQUE(job_type, idempotency_key)
```

**Finding:** REUSE

P9 should add the equivalent owner-local migration for `nex-wa`, rather than
inventing a WA-specific queue schema.

---

# 9. Concurrent Worker Claim Is Already Supported

`SqlAlchemyJobQueue` selects runnable PostgreSQL jobs using:

```text
FOR UPDATE SKIP LOCKED
```

and orders by:

```text
available_at
created_at
job_id
```

This supports multiple concurrent workers without requiring an external
message broker for Foundation.

**Finding:** REUSE

This source-backs the P9 PAD decision that:

```text
nex-wa-evidence-consumer-1
nex-wa-evidence-consumer-2
...
```

may safely share one WA `service_jobs` queue.

---

# 10. Queue Retry / Dead-Letter / Replay Is Already Implemented

The shared JobQueue already provides:

```text
JobRetryPolicy
plan_job_retry()
dead_letter_job()
JobReplayPolicy
plan_dead_letter_replay()
```

with bounded exponential-style retry configuration.

**Finding:** REUSE

P9 does not need a second retry framework.

---

# 11. Shared Worker Runner Already Exists

Current source:

```text
services/_shared/nex_runtime/worker_runner.py
```

already provides general worker execution helpers including:

```text
WorkerRunnerConfig
run_worker_once()
run_worker_batch()
JobQueue claim
heartbeat integration
service log integration
job completion/failure
```

**Finding:** REUSE

P9 should compose a WA evidence consumer from this existing shared worker
foundation wherever possible.

---

# 12. Shared Worker Heartbeat Already Exists

Current source:

```text
services/_shared/nex_runtime/worker_heartbeats.py
```

provides:

```text
WorkerHeartbeatEmitter
SqlAlchemyWorkerHeartbeatStore

STARTING
IDLE
BUSY
STOPPING
STOPPED
ERROR
```

**Finding:** REUSE WITH SMALL GAP

The current static service list includes:

```text
nex-oa
nex-ag
nex-ae-api
nex-cx
nex-mo
nex-wc
nex-eos
```

but not:

```text
nex-wa
```

P9 must extend the service vocabulary.

---

# 13. Worker Heartbeat Persistence Pattern Already Exists

Common migration:

```text
0112_service_worker_heartbeat_foundation.sql
```

is already used by multiple services.

P8 also added an EOS-specific current migration for worker heartbeat.

**Finding:** REUSE

P9 should use the existing common heartbeat model rather than inventing a
WA-only liveness store.

---

# 14. Service Log / Operational Observability Requires WA Registration

The shared runtime contains:

```text
service_logs.py
operational_events.py
worker_heartbeats.py
```

which are reusable patterns.

However several common modules maintain static service identity catalogs that
do not yet contain `nex-wa`.

**Finding:** GAP / SMALL CROSS-CUTTING CHANGE

Contract Closure should inventory every static service registry that requires
`nex-wa`.

---

# 15. Generic Deployment Catalog Does Not Yet Know NeX-WA

Current default deployment artifact catalog contains first-class artifacts for:

```text
nex-oa
nex-ae
nex-cx
nex-mo
nex-ag
nex-ae-web
```

P8-DEMO added WC/EOS through later/demo-specific composition.

There is no:

```text
nex-wa-runtime
```

artifact or process binding.

**Finding:** GAP

P9 must add a first-class WA deployment artifact and process ownership.

---

# 16. Recommended WA Deployment Artifact

**Recommendation:**

```text
artifact_id = nex-wa-runtime
owner       = nex-wa
kind        = python-service
```

Initial process bindings:

```text
nex-wa-api
nex-wa-evidence-consumer
```

Both may share one runtime image.

Exact OCI target names belong to Contract Closure / implementation planning.

---

# 17. PostgreSQL Test Target Catalog Does Not Yet Know NeX-WA

Current `postgres_targets.py` does not define a WA target.

**Finding:** GAP

P9 should add:

```text
NEX_WA_TEST_DATABASE_URL
NEX_WA_DATABASE_URL

expected test DB:
nex_wa_test

expected role:
nex_wa_user
```

Exact production/dev naming should align with current deployment conventions.

---

# 18. Recommended WA Persistence Boundary

**Recommendation:**

```text
NeX-WA owner-local PostgreSQL
```

with no direct cross-service DB reads.

Candidate database identities:

```text
nex_wa_dev
nex_wa_test
```

No cross-database foreign key should be introduced.

---

# 19. AE RuntimeJob Must Not Be Reused

P5 already accepted a strict separation:

```text
service_jobs
= general service background work

ae_runtime_job
= AgentExecution / ExecutableStep progression
```

P9 evidence ingestion is general service background processing.

**Finding:** SOURCE-BACKED DECISION

Therefore:

```text
WA_EVIDENCE_INGEST
```

belongs in WA `service_jobs`, not `ae_runtime_job`.

---

# 20. No New Broker Is Required for Foundation

Because current shared JobQueue already supports:

```text
PostgreSQL persistence
idempotent enqueue
concurrent SKIP LOCKED claim
retry
dead letter
replay
worker heartbeat
```

P9 has no source-backed requirement for:

```text
Kafka
RabbitMQ
NATS
Redis Streams
```

**Finding:** RECOMMENDATION / PRESERVE PAD

A separate broker should remain deferred until measured operational evidence
demonstrates need.

---

# 21. WC WorkResult Is a Strong Evidence Object

Current WC WorkResult persistence:

```text
wc_work_result
```

stores:

```text
tenant_id
result_id
work_item_id
revision_no
result_type
result_schema_ref
result_hash
result_payload
source_execution_ref
claim_id
claim_generation
assignment_id
submitted_agent_id
authorization_revision_hash
authorization_checked_at
submitted_at
```

and enforces unique:

```text
(tenant_id, work_item_id, revision_no)
```

**Finding:** REUSE AS AGENT WORK EVIDENCE

WC WorkResult is a strong authoritative source for Agent-performed work.

---

# 22. WC WorkResult Is Currently Agent-Only

Current route:

```text
POST /api/v1/work-items/{work_item_id}/results
```

authorizes only:

```text
nex-ae-api
```

and explicitly rejects other callers.

The error contract states that only `nex-ae-api` may submit an Agent WorkResult.

**Finding:** SOURCE-BACKED LIMITATION

Therefore the current WC WorkResult MUST NOT be described as a general Human
work-completion source.

This materially narrows the initial P9 source model.

---

# 23. Human Work Evidence Cannot Be Assumed from WC WorkResult

The P9 PAD conceptually identified WC WorkResult as a potential general source.

Current source proves:

```text
WC WorkResult
= current Agent result submission path
```

not:

```text
WC WorkResult
= general Human + Agent result path
```

**Finding:** GAP / PAD REFINEMENT

Human work evidence needs a different current source or a future explicit WC
contract.

---

# 24. WC WorkResult Already Emits a Durable Outbox Event

Current WC persistence creates:

```text
WORK_RESULT_SUBMITTED
```

outbox events.

Current delivery code bridges pending outbox events into shared JobQueue jobs.

**Finding:** REUSE PATTERN

This is a useful pattern for WA source delivery, but not yet a multi-subscriber
event bus.

---

# 25. WC WorkResult Event Delivery Is Currently Single-Consumer to AE

Current `HttpWorkResultEventClient` delivers to:

```text
AE /internal/v1/work-result-events
```

The WC outbox has one delivery-state progression for that event.

After AE acknowledgment, the outbox event is marked delivered.

**Finding:** GAP

The current implementation does not provide generic fan-out to:

```text
AE
+
WA
+
other subscribers
```

for the same source event.

---

# 26. Do Not Assume Existing WC Outbox Is a Multi-Subscriber Bus

P9 should not bolt WA onto the current WC outbox by pretending one
`delivery_state` represents independent AE and WA delivery.

**Recommendation:**

Contract Closure should choose one of:

```text
A. new multi-target outbox delivery model
B. dedicated safe WA projection event
C. source-reference intake + WA owner-API verification
```

For Foundation simplicity, option C is the leading candidate unless a clean
existing projection path is found.

---

# 27. AE AgentResult Is an Excellent WA Source

Current `AgentResult` already provides:

```text
tenant_id
result_id
agent_execution_id
agent_type
agent_id
project_id
status
structured_result
business_refs
artifact_refs
evidence_refs
provenance
result_hash
created_at
```

**Finding:** REUSE

This fits the P9 reference-first model extremely well.

---

# 28. AgentResult Supports All Four Agent Types

Current contract accepts:

```text
IA
CA
PA
EA
```

**Finding:** SOURCE-BACKED

This validates the PAD actor approach:

```text
actor_type = AGENT
agent_type_snapshot = IA | CA | PA | EA
```

rather than four separate WA identity domains.

---

# 29. Background AgentResult Carries WC Claim Lineage

For:

```text
CA
PA
EA
```

AgentResult requires complete:

```text
project_id
source_work_item_ref
source_claim_ref
source_claim_generation
source_claimant_agent_id
source_assignment_ref
```

and source claimant Agent must match the execution Agent.

**Finding:** REUSE

This is strong Project/work attribution evidence for WA.

---

# 30. IA AgentResult Is Project-Neutral by Contract

Current IA AgentResult forbids:

```text
project_id
WC claim lineage
```

**Finding:** SOURCE-BACKED LIMITATION

P9 must not infer an IA Project merely because an IA artifact or conversation
mentions a Project.

IA Project attribution requires another authoritative source or explicit
Project reference.

---

# 31. AgentResult Already Rejects Raw Private Content

Current AgentResult validation explicitly enforces:

```text
references and hashes
not raw private content
```

**Finding:** REUSE / STRONG FIT

This aligns with WA's reference-first privacy model.

---

# 32. AgentResult Has an Existing WA_PROJECTION Schema Hook

Migration `2006_ae_agent_result.sql` allows delivery target:

```text
WA_PROJECTION
```

and marks projection-like targets as non-required.

**Finding:** SOURCE-BACKED SCHEMA HOOK

This is evidence that future WA projection was anticipated at the schema level.

---

# 33. WA_PROJECTION Is Not Currently Implemented as Runtime Delivery

Current AgentResult `_pending_delivery()` creates exactly one required
delivery:

```text
IA       -> WORKSPACE_RESULT
CA/PA/EA -> WC_WORK_RESULT
```

It does not currently create a second:

```text
WA_PROJECTION
```

delivery.

Repository retrieval paths also assume the current canonical result delivery.

**Finding:** GAP

`WA_PROJECTION` is reserved contract space, not a completed WA integration.

---

# 34. Potential AE-to-WA Integration Options

Contract Closure should compare:

```text
Option A
Extend AgentResult delivery to optional WA_PROJECTION

Option B
Create an AE safe WA source projection endpoint
and enqueue source refs in WA

Option C
Create a dedicated AE outbox projection for WA
```

**Recommendation:**

For minimal P9 Foundation, prefer a design that does not destabilize the
required IA/WC result delivery semantics.

---

# 35. AE Artifact Is a Strong Human-Oriented Evidence Candidate

Current Artifact record stores:

```text
artifact_id
artifact_type
artifact_status
owner_actor_ref
workspace_ref
source_refs
versions
files
links
created_at
updated_at
```

`owner_actor_ref` includes:

```text
actor_type
actor_id
tenant_id
```

**Finding:** REUSE CANDIDATE

This gives P9 a current source for user-owned work artifacts.

---

# 36. Artifact Source References Already Carry Integrity Evidence

Artifact source refs can carry:

```text
structured_draft_content_hash
citation_claims_hash
validation_result_hash
retrieval_package_id
retrieval_package_hash
quality_summary
```

**Finding:** REUSE

WA should reference this source metadata rather than duplicate rendered
Artifact bytes.

---

# 37. Artifact Ownership Vocabulary Needs WA Normalization

Current Artifact actor type defaults to:

```text
user
```

where P9 PAD proposes:

```text
HUMAN
AGENT
```

**Finding:** GAP / NORMALIZATION REQUIRED

WA should deterministically map source actor vocabulary into its canonical
ActorRef contract.

It should not assume every source system already uses the WA vocabulary.

---

# 38. Artifact Is Not Automatically Project-Attributed

Current Artifact ownership is strongly scoped to:

```text
tenant
owner/user
workspace
```

but Project attribution is not automatically guaranteed by the Artifact
record itself.

**Finding:** SOURCE-BACKED LIMITATION

P9 must separately establish ProjectRef when a WorkAsset is Project-scoped.

---

# 39. Human Evidence Initial Source Strategy

Because WC WorkResult is Agent-only today, the smallest current Human source
set is likely:

```text
AE Artifact owner/creator lineage
+
controlled Manual/Import evidence if required
```

with Project attribution verified separately.

**Finding:** RECOMMENDATION

P9 should not expand WC Human submission semantics merely to satisfy WA
Foundation unless the business requirement proves necessary.

---

# 40. OA Owns Human Identity

Current OA employee batch resolution maps:

```text
employee_id
→ credential
→ subject_id
→ subject lifecycle
→ tenant membership
```

**Finding:** REUSE

WA Human identity should be:

```text
actor_type = HUMAN
actor_ref  = OA subject_id
```

---

# 41. OA Employee Resolver Is Not an HR Employee Master

The current resolver is identity/tenant authority.

It does not provide:

```text
salary
compensation
payroll
HR PII master
labor cost
```

**Finding:** SOURCE-BACKED LIMITATION

This remains consistent with Golden C ownership.

---

# 42. Employee Number Should Not Be WA Identity

If a source contains only an employee number, WA may use OA to resolve it.

Once resolved, WA should persist/reference:

```text
OA subject_id
```

as the Human actor authority.

**Recommendation:** PRESERVE PAD

---

# 43. EOS Already Owns Project Identity

Current EOS owns:

```text
NVTProject
Project
Project hierarchy
Project lifecycle
```

**Finding:** REUSE

WA must not create a parallel Project master.

---

# 44. EOS Already Owns Project Membership

Current:

```text
eos_project_member
```

supports:

```text
subject_id
project_id
OWNER
MANAGER
MEMBER
VIEWER
ACTIVE
REMOVED
versioned lifecycle
```

**Finding:** REUSE

This is the authoritative Human Project relationship source.

---

# 45. ProjectMember Uses OA subject_id

EOS stores Human identity as opaque:

```text
subject_id
```

without cross-service database foreign keys.

**Finding:** REUSE / ARCHITECTURAL FIT

WA should follow the same pattern.

---

# 46. WA Must Not Read EOS ProjectMember Directly

Although `eos_project_member` is an ideal validation source, P9 inherits the
no-cross-service-DB rule.

**Recommendation:**

Use:

```text
EOS owner API
or
admitted safe source projection
```

for Project validation.

---

# 47. Agent Project Attribution Is Stronger Than Human Artifact Attribution

For background Agent work, current source can provide:

```text
AgentResult.project_id
+
WC claim/work lineage
```

For Human artifacts, current source does not always provide equivalent Project
authority.

**Finding:** MATERIAL SOURCE ASYMMETRY

P9 should support different Human and Agent attribution adapters rather than
forcing identical source rules.

---

# 48. Human and Agent Share WA Architecture, Not Necessarily Source Logic

**Recommendation:**

```text
ActorRef
  HUMAN | AGENT
```

is common.

But admission adapters may differ:

```text
Human:
OA + Artifact/Manual source + EOS Project verification

Agent:
AE AgentResult + WC lineage + EOS Project verification
```

This is consistent with PAD v1.2.

---

# 49. Source Admission Should Be Adapter-Based

P9 should avoid one giant intake handler with source-specific branches.

Recommended conceptual boundary:

```text
WaEvidenceSourceAdapter
```

with source implementations such as:

```text
AeAgentResultSourceAdapter
AeArtifactSourceAdapter
WcWorkResultSourceAdapter
ManualEvidenceSourceAdapter   [optional/deferred]
```

Exact interface is Contract Closure scope.

---

# 50. Source Adapter Responsibility

Each adapter should normalize only authoritative source facts.

Candidate normalized projection:

```text
tenant_id
source_type
source_ref
source_revision/event_id
source_hash
actor_type
actor_ref
agent_type_snapshot?
project_ref?
artifact_refs[]
evidence_refs[]
business_object_refs[]
occurred_at
classification
```

The adapter must not create contribution authority.

---

# 51. WA Intake Should Enqueue References, Not Source Payloads

Current WC JobQueue delivery already demonstrates a references-only payload:

```text
outbox_id
event_id
```

**Finding:** REUSE PATTERN

P9 should mirror this principle.

Recommended WA job payload:

```text
source_type
source_ref
source_event_id / source_revision
source_hash
```

with optional bounded routing refs only.

---

# 52. JobQueue Is Not Evidence Authority

A Job means:

```text
process this source
```

not:

```text
this evidence is true
```

**Recommendation:**

The worker must re-resolve/verify the authoritative source before creating
WorkEvidence.

This preserves restart and replay correctness.

---

# 53. Queue-Level Idempotency Is Already Available

Shared JobQueue deduplicates by:

```text
(job_type, idempotency_key)
```

**Finding:** REUSE

P9 should derive the key from stable source identity.

---

# 54. Evidence-Level Idempotency Is Still Required

Current JobQueue guarantees are not enough for:

```text
WA insert commits
worker crashes
job completion not committed
job retries
```

**Finding:** NEW WA REQUIREMENT

P9 needs a second unique evidence identity in WA persistence.

---

# 55. Recommended Evidence Identity

Not frozen, but the source-backed candidate is:

```text
tenant_id
source_type
source_ref
source_revision/event_id
evidence_kind
```

or an exact semantic hash derived from those values.

**Finding:** OPEN / CONTRACT CLOSURE

---

# 56. Evidence Conflict Rule

Recommended semantic contract:

```text
same source identity
+ same semantic hash
→ return/reuse existing WorkEvidence

same source identity
+ different semantic hash
→ typed conflict / correction path
```

This is required for safe replay.

---

# 57. Append-Only / Supersession Is Still a New WA Requirement

No current WA table exists.

The PAD requires evidence not to be silently overwritten.

**Finding:** GAP

P9 persistence must provide:

```text
immutable admitted evidence
+
explicit supersession/invalidation lineage
```

Exact columns belong to Contract Closure.

---

# 58. Approval-Free Background Admission Is Consistent with Current Sources

Current AgentResult, WorkResult, Artifact and outbox patterns are system-owned
facts with durable identity/hash/lineage.

None requires the Artifact creator to re-approve its existence merely to
persist technical evidence.

**Finding:** SOURCE-BACKED FIT

The PAD invariant:

```text
Evidence Admission != Business Approval
```

is compatible with current P8 architecture.

---

# 59. No WC Approval Is Needed for WA Intake

WA intake is not a new delegated business task.

**Recommendation / PAD PRESERVED:**

Do not create:

```text
WorkItem
ApprovalWorkItem
Human Gate
```

just to project an existing authoritative result into WA.

---

# 60. No NSL Is Needed for WA Foundation Intake

Current source provides all mechanisms needed for:

```text
source event/reference
JobQueue
worker
verification
PostgreSQL persistence
```

without NSL.

**Finding:** PAD PRESERVED

NSL remains deferred.

---

# 61. Minimal WA Runtime Is Source-Feasible

The source audit supports the PAD runtime:

```text
nex-wa-api
        +
nex-wa-evidence-consumer
        +
nex_wa PostgreSQL
```

with shared runtime reuse.

**Finding:** RECOMMENDATION

No third WA scheduler/dispatcher process is justified.

---

# 62. Initial Job Type Can Remain One

No current source requires distinct worker classes for separate evidence types.

**Recommendation:**

Start with:

```text
WA_EVIDENCE_INGEST
```

and route within the worker by bounded `source_type`.

Do not create multiple Job types until operational evidence requires them.

---

# 63. Initial Source Set Should Be Smaller Than PAD's Candidate List

PAD listed many possible source types.

Current executable source most strongly supports:

```text
AE_AGENT_RESULT
AE_ARTIFACT
WC_WORK_RESULT
```

**Recommendation:**

Use these as the first audited source candidates.

Treat other source types as deferred until source contracts are proven.

---

# 64. EOS Business Events Are Not Required for P9 Foundation Entry

EOS business evidence may later be useful.

However P9's core purpose can be proven with:

```text
AgentResult
Artifact
WorkResult
Project/ProjectMember validation
```

**Recommendation:** DEFER

Avoid pulling EOS business-event ingestion into initial WA evidence slices
unless required by a concrete Foundation acceptance case.

---

# 65. Manual / Import Evidence Can Be Deferred

PAD allows Manual/Import evidence.

Current P8 source does not provide a canonical WA Manual Evidence contract.

**Finding:** GAP / OPTIONAL

Recommendation:

```text
P9 Foundation core
= system-generated evidence first

Manual/Import
= later bounded slice if required
```

This reduces P9 implementation scope.

---

# 66. Human Evidence Remains the Main Source-Contract Gap

Agent evidence has strong current lineage.

Human evidence does not yet have an equivalent generic WorkResult path.

**Finding:** PRIMARY P9 SOURCE GAP

Contract Closure must explicitly choose the minimal Human evidence source
instead of assuming one.

---

# 67. Recommended Human Foundation Path

Leading minimal option:

```text
AE Artifact
  owner_actor_ref
  workspace/source hashes
        ↓
WA source-reference intake
        ↓
OA subject validation
        ↓
optional EOS Project validation
        ↓
WorkEvidence
```

This proves Human evidence ingestion without expanding WC.

**Recommendation:** LEADING CANDIDATE

---

# 68. Recommended Agent Foundation Path

Leading option:

```text
AE AgentResult
  agent_id
  IA/CA/PA/EA
  project_id where authoritative
  artifact/evidence/business refs
  result_hash
  WC claim lineage for background Agent
        ↓
WA source-reference intake
        ↓
WorkEvidence
```

**Recommendation:** LEADING CANDIDATE

---

# 69. WC WorkResult Should Be Additional Agent Evidence

For CA/PA/EA work, WC WorkResult adds:

```text
WorkItem context
claim
assignment
submission authority
result hash
```

This is useful as supporting evidence.

**Recommendation:**

Do not necessarily create a duplicate top-level WorkAsset for both AgentResult
and WorkResult.

Contract Closure should decide whether one is:

```text
primary source
```

and the other:

```text
supporting evidence ref
```

to avoid double-counting one unit of work.

---

# 70. Double-Counting Is a Real P9 Risk

The same background Agent work can appear as:

```text
AE AgentResult
        ↓
published as
        ↓
WC WorkResult
```

If WA independently counts both as two contributions, the result is wrong.

**Finding:** MATERIAL GAP

P9 needs a source-equivalence / lineage rule.

---

# 71. Recommended Source Equivalence Rule

For background Agent work:

```text
AgentResult.agent_execution_id
+
WC WorkResult.source_execution_ref
```

can bind the two records into one logical work lineage.

**Recommendation:**

One WorkAsset may bind both source references while retaining separate
WorkEvidence items.

This avoids double-counting.

Exact model belongs to Contract Closure.

---

# 72. Artifact Double-Counting Also Requires Care

An AgentResult may reference one or more Artifacts.

The same Artifact may also arrive through Artifact source intake.

**Finding:** MATERIAL GAP

WA must distinguish:

```text
work unit
vs
supporting artifact
```

rather than treating every source record as an independent contribution unit.

---

# 73. WorkAsset Granularity Cannot Be Frozen Yet

Current source supports several possible anchors:

```text
AgentExecution
WorkResult
Artifact
business deliverable
```

No current executable contract proves which must be the single canonical
WorkAsset granularity.

**Finding:** OPEN

Contract Closure must decide the minimum v1 granularity after avoiding
double-counting.

---

# 74. WorkEvidence and WorkAsset Should Probably Remain Separate Concepts

Source audit reinforces the PAD distinction:

```text
WorkEvidence
= atomic source fact

WorkAsset
= normalized business-relevant work aggregation anchor
```

because one work execution can have:

```text
AgentResult evidence
WorkResult evidence
Artifact evidence
```

without representing three independent work contributions.

**Recommendation:** KEEP SEPARATE LOGICALLY

Whether both require physical tables in the first slice remains open.

---

# 75. WorkFact Can Potentially Be Deferred

Many initial normalized facts could live on WorkEvidence or a projection.

**Recommendation:**

Do not automatically create:

```text
wa_work_fact
```

as a separate table in P9.2 unless Source/Contract Closure demonstrates value.

This keeps Foundation small.

---

# 76. ContributionCandidate Persistence Should Be Later

P9.2/P9.3 should focus on reliable evidence.

**Recommendation:**

Delay physical:

```text
wa_contribution_candidate
```

until P9.5.

This prevents early schema from encoding an immature contribution method.

---

# 77. Minimal Initial WA-Owned Persistence

Recommended P9 Foundation starting point:

```text
schema_migrations
service_jobs
service_worker_heartbeats

wa_work_evidence
wa_work_asset
```

Potentially:

```text
wa_evidence_source_binding
```

only if needed to cleanly support multi-source lineage.

**Finding:** RECOMMENDATION / NOT YET FROZEN

---

# 78. Do Not Copy Full Source JSON by Default

Current AgentResult/Artifact/WorkResult can contain larger structured payloads.

PAD says reference-first.

**Recommendation:**

WA should persist:

```text
source identity
source hash/version
normalized bounded facts
source refs
evidence refs
```

not uncontrolled copies of:

```text
AgentResult envelope
WorkResult payload
Artifact bytes
raw generated content
```

---

# 79. Source Projection Endpoints May Be Needed

Because WA cannot read source DBs directly, P9 may need owner APIs such as:

```text
AE AgentResult safe projection by exact ref
AE Artifact safe projection by exact ref
WC WorkResult safe projection by exact ref
EOS Project/ProjectMember verification projection
OA subject verification projection
```

**Finding:** GAP

Exact endpoints should be Contract Closure decisions.

---

# 80. Existing Public/User APIs May Be Too Broad or Wrongly Scoped

Some existing source APIs are browser-owner or service-specific.

P9 should not reuse them blindly if they expose:

```text
too much payload
wrong authorization semantics
user-facing projection
```

**Recommendation:**

Prefer narrow service-to-service source verification contracts.

---

# 81. New WA Source APIs Should Return Safe Projections

If new source verification endpoints are added, they should return only what
WA needs.

Example:

```text
source_ref
tenant_id
source_hash
actor_ref
agent_type?
project_ref?
artifact_refs[]
evidence_refs[]
occurred_at
classification
```

No raw prompt, credentials, hidden reasoning, or unrestricted source payload.

---

# 82. P9 Does Not Need Remote Generation for Source Admission

All initial source verification and normalization can be deterministic.

**Finding:** RECOMMENDATION / PAD PRESERVED

No NeX-MO provider is needed for:

```text
P9.2 WorkEvidence foundation
P9.3 source intake
P9.4 actor/Project attribution
```

---

# 83. Contribution Calculation Can Also Start Deterministic

The initial contribution method can be deliberately simple and evidence-based.

No source requirement forces an LLM.

**Recommendation:**

Remote generation remains optional/deferred.

---

# 84. Project Attribution Must Be Source-Specific

Strong source examples:

```text
CA/PA/EA AgentResult.project_id
WC claimed-work lineage
```

Weak/absent source example:

```text
IA Artifact with Project name only in content
```

**Finding:** SOURCE-BACKED

WA must not infer Project authority from free text.

---

# 85. Human Project Attribution Requires Current EOS Relationship When Needed

For Project-scoped Human evidence, the likely authoritative validation is:

```text
OA subject
+
EOS Project
+
EOS ProjectMember
```

at the relevant evidence time/policy boundary.

**Finding:** RECOMMENDATION

Exact historical-effective-time semantics need Contract Closure.

---

# 86. Current ProjectMember Has Effective Period Data

`eos_project_member` contains:

```text
valid_from
valid_to
status
version
```

**Finding:** REUSE

This may support time-aware Human Project attribution.

---

# 87. Agent Project Attribution May Not Require ProjectMember

Agents are not OA employees.

Background Agent project identity is already present in AgentExecution/AgentResult
lineage.

**Finding:** RECOMMENDATION

Do not force Agent identities into EOS Human ProjectMember rows.

---

# 88. P9 Actor Contract Should Preserve Source Identity

Recommended normalized actor:

```text
actor_type = HUMAN | AGENT
actor_ref
```

For Agent:

```text
agent_type_snapshot = IA | CA | PA | EA
```

For Human:

```text
OA subject_id
```

**Finding:** PAD CONFIRMED

---

# 89. P9 Should Store Source Agent Type Snapshot

Because Agent type is source-backed and useful analytically:

```text
IA
CA
PA
EA
```

should be preserved on normalized evidence or source binding.

**Recommendation:**

Treat it as provenance, not identity authority.

---

# 90. P9 Evidence Processing Should Be Approval-Free

Current source facts are already authorized at their source boundaries.

WA's job is to verify and project them.

**Finding:** PAD CONFIRMED

No new artifact-creator or manager approval is justified for ordinary
system-generated evidence ingestion.

---

# 91. Business Consequence Gate Remains Downstream

Source audit finds no reason to move Golden C business authority into WA.

**Recommendation:**

Keep:

```text
WorkEvidence
→ ContributionCandidate
```

automatic/candidate-oriented.

Later:

```text
ContributionCandidate
→ finalized 0.05 MM
→ monetary cost
```

belongs to Golden C.

---

# 92. Existing Result Delivery Reliability Should Not Be Duplicated Blindly

AE result delivery has sophisticated required delivery and reconciliation
semantics.

WA projection is non-required evidence projection in Foundation.

**Recommendation:**

Do not block AgentExecution completion solely on WA projection unless a future
business requirement explicitly changes that boundary.

This is consistent with existing `WA_PROJECTION` being non-required in schema.

---

# 93. WA Failure Should Not Retroactively Fail Source Work

If:

```text
AgentResult SUCCEEDED
```

but WA projection temporarily fails, the Agent work itself should not become
FAILED.

**Recommendation:**

Treat WA ingestion as separately retryable background evidence processing.

This is a key decoupling invariant for Contract Closure.

---

# 94. Source Work Completion and WA Admission Need Separate State

Recommended separation:

```text
Source business/result state
= owned by AE/WC/EOS

WA intake state
= QUEUED/RUNNING/ADMITTED/FAILED/CONFLICT...
```

**Finding:** PAD CONFIRMED

Do not overwrite source business state based on WA processing outcome.

---

# 95. WA Backpressure Should Affect WA Intake, Not Source Authority

If WA queue is full or delayed:

```text
source result remains authoritative
WA projection is delayed/retryable
```

**Recommendation:**

Backpressure should not make an already valid AgentResult or WorkResult invalid.

---

# 96. WA Queue Payload Must Be Privacy-Safe

Current shared JobQueue allows JSON payloads, but P9 must constrain its own use.

**Recommendation:**

Allow only:

```text
source refs
hashes
bounded routing metadata
trace/correlation refs
```

Reject:

```text
raw prompts
artifact bytes
private source text
credentials
salary/PII payloads
```

---

# 97. Shared JobQueue Does Not Enforce WA-Specific Payload Privacy

The common JobQueue is general-purpose.

**Finding:** GAP

P9 needs its own:

```text
WA_EVIDENCE_INGEST payload validator
```

even while reusing the common queue implementation.

---

# 98. Shared Worker Heartbeat Service Vocabulary Must Be Extended

`nex-wa` is absent from the shared `SERVICE_IDS`.

**Finding:** SMALL IMPLEMENTATION GAP

This is required before using `WorkerHeartbeatEmitter(service_id="nex-wa")`.

---

# 99. Shared Service Log Vocabulary Also Needs Review

Static service ID lists exist in logging/observability modules.

**Finding:** SMALL IMPLEMENTATION GAP

Contract Closure should define a single P9 checklist of common registries that
must accept `nex-wa`.

---

# 100. Runtime Endpoint Registry Needs WA Addition

Current shared endpoint registry does not include NeX-WA.

**Finding:** GAP

Candidate:

```text
NEX_WA_BASE_URL
```

and an assigned internal port are needed.

Exact port should be chosen in Contract Closure.

---

# 101. Runtime Topology Must Add WA Processes

Generic topology supports process kinds:

```text
api
web
worker
daemon
```

**Finding:** REUSE

WA can use:

```text
api    -> nex-wa-api
worker -> nex-wa-evidence-consumer
```

without adding a new process kind.

---

# 102. OCI Build Framework Is Reusable

Existing deployment artifact machinery supports Python service artifacts.

**Finding:** REUSE

P9 needs catalog extension, not a new container build system.

---

# 103. WA API Should Remain Thin

Based on current architecture, the API should primarily:

```text
authenticate/authorize caller
validate intake request
derive/validate source identity
build idempotency key
enqueue WA_EVIDENCE_INGEST
return admission receipt
serve bounded WA reads
```

It should not perform long evidence normalization inline.

**Recommendation:** PRESERVE PAD

---

# 104. WA Consumer Should Own Background Processing

The consumer should:

```text
claim Job
resolve source adapter
fetch/verify source projection
normalize actor
verify Project if applicable
verify source hash/version
deduplicate WorkEvidence
persist evidence/asset atomically as applicable
complete/retry/fail Job
emit heartbeat/log/evidence
```

**Recommendation:** IMPLEMENTATION DIRECTION

---

# 105. Atomicity Boundary Needs Contract Closure

Open question:

Should:

```text
WorkEvidence insert
+
WorkAsset create/update
```

be one local transaction?

For initial Foundation, this is likely desirable.

**Finding:** OPEN

Contract Closure should decide exact local UoW.

---

# 106. WorkAsset Update Semantics Need Care

If a WorkAsset aggregates multiple immutable evidence records, adding evidence
may change its projection.

**Finding:** OPEN

Potential model:

```text
WorkEvidence immutable
WorkAsset versioned aggregate
```

rather than mutable evidence.

---

# 107. Source Correction Semantics Need a First-Class Contract

Current sources may change/revise.

WA needs:

```text
SUPERSEDE
INVALIDATE
CORRECT
```

or equivalent lineage semantics.

**Finding:** GAP

Do not use silent UPDATE as the default correction mechanism.

---

# 108. Retention Requires Later Explicit Decision

AE Artifact already has its own retention lifecycle.

WA evidence may outlive or reference artifacts that later become archived or
deleted.

**Finding:** OPEN

P9 must decide whether WA retains:

```text
identity/hash/provenance
```

after source content retention removes bytes.

This should be privacy- and audit-driven.

---

# 109. WA Should Not Copy Artifact Bytes for Retention

**Recommendation:**

If Artifact content is deleted under AE retention, WA should retain only the
allowed evidence identity/provenance required by its own policy.

This preserves service ownership.

---

# 110. Data Classification Must Propagate Conservatively

Source classification may differ.

**Recommendation:**

WA classification must:

```text
preserve
or strengthen
```

source sensitivity.

It must not silently downgrade.

Exact classification merge rule is Contract Closure scope.

---

# 111. Detailed Human Evidence Is Privacy-Sensitive

Human WorkEvidence can reveal:

```text
work timing
Project participation
artifact history
activity pattern
```

**Finding:** PAD CONFIRMED

P9 requires privacy-scoped reads from the first production design.

---

# 112. Source Audit Does Not Support Employee Performance Scoring

No current P8 contract makes WorkResult/Artifact counts an employee
performance authority.

**Finding:** OUT OF SCOPE

Do not add a performance score in P9 Foundation.

---

# 113. Source Audit Does Not Support Automatic Accounting MM

No current source provides a reliable authoritative mapping:

```text
evidence count
→ MM
```

**Finding:** OUT OF SCOPE

P9 can later produce a candidate, not final MM.

---

# 114. Golden C Handoff Remains Valid

P9 should eventually provide a bounded candidate with:

```text
actor_ref
project_ref
period
candidate value
evidence set/hash
method/version
confidence/completeness
```

**Finding:** RECOMMENDATION

Golden C performs final confirmation and monetary conversion.

---

# 115. Candidate Method Must Avoid Source Double-Counting

Before P9.5, the method must understand lineage such as:

```text
AgentResult
→ WC WorkResult
→ Artifact refs
```

as one work chain, not independent work units.

**Finding:** CRITICAL FUTURE REQUIREMENT

---

# 116. P9.2 Should Not Implement Contribution Logic

**Recommendation:**

P9.2 closes only:

```text
WA service
WA DB
JobQueue
worker
WorkEvidence
minimum WorkAsset
```

No contribution formula.

---

# 117. P9.3 Should Close Source Intake

Recommended scope:

```text
AE AgentResult adapter
AE Artifact adapter
optional WC WorkResult supporting adapter
idempotency
retry/restart
source equivalence
```

---

# 118. P9.4 Should Close Actor and Project Attribution

Recommended scope:

```text
HUMAN/AGENT normalization
IA/CA/PA/EA snapshot
OA Human verification
EOS Project verification
EOS ProjectMember validation where needed
```

---

# 119. P9.5 May Introduce Candidate Calculation

Only after evidence lineage is reliable should P9.5 add:

```text
ProjectContributionCandidate
HumanEffortCandidate
AgentEffortCandidate
```

if still required.

---

# 120. P9.6 Should Close Privacy / Query / Reliability

Candidate focus:

```text
bounded queries
privacy projection
retention
retry/dead-letter operator visibility
replay
backpressure
worker scaling
```

---

# 121. P9.7 Should Be a Protected Foundation E2E

Recommended protected journey:

```text
1. Human-owned Artifact exists.
2. AgentResult exists with PA/EA/CA lineage.
3. Multiple WA intake requests arrive concurrently.
4. WA queue deduplicates source identities.
5. Multiple workers safely claim with PostgreSQL.
6. Source projections are verified.
7. Human and Agent WorkEvidence are persisted.
8. AgentResult / WC WorkResult lineage is not double-counted.
9. Restart/retry creates no duplicate evidence.
10. No Human Approval occurs for ordinary evidence admission.
11. No NSL is required.
12. No scheduler, payroll, cost or P/L is created.
13. PostgreSQL migration/current-state evidence passes.
14. Repository Full Gate and zero-residue closure pass.
```

---

# 122. Recommended Initial Source Priority

Priority 1:

```text
AE_AGENT_RESULT
```

Reason:

```text
strong hash
Agent identity
Agent subtype
Project for background Agents
artifact/evidence/business refs
immutable result semantics
```

Priority 2:

```text
AE_ARTIFACT
```

Reason:

```text
Human owner scope
source hashes
artifact identity
existing privacy/retention
```

Priority 3:

```text
WC_WORK_RESULT
```

Reason:

```text
strong supporting Agent work/claim/assignment evidence
but current event delivery is AE-specific
and may duplicate AgentResult lineage
```

---

# 123. Sources Deferred from Initial Foundation

Recommended defer:

```text
EOS business-operation events
Manual/Import
CX retrieval/generation events
MO model telemetry
service logs
generic operational events
```

unless Contract Closure identifies a concrete Foundation acceptance need.

---

# 124. Minimum New P9 Source Code Surface

Likely new owner source:

```text
services/nex-wa/nex_wa/
  main.py
  app.py
  persistence.py
  work_evidence.py
  work_assets.py
  source_admission.py
  source_adapters.py
  evidence_jobs.py
  evidence_worker.py
  queries.py
```

This is illustrative, not frozen.

---

# 125. Minimum New P9 Database Surface

Likely:

```text
database/nex-wa/migrations/
  baseline
  service_jobs
  worker_heartbeat
  wa_work_evidence
  wa_work_asset
```

Exact numbering must follow current repository migration conventions.

---

# 126. Minimum Cross-Service Changes

Expected small changes outside WA:

```text
shared service registries add nex-wa
runtime endpoint registry add nex-wa
deployment artifact/process catalog add nex-wa
PostgreSQL target catalog add nex-wa
source-safe projection endpoints where required
service-token scopes/audience for WA calls
```

The exact set must be closed before implementation slices.

---

# 127. No Existing Source Justifies a Large P9

The audit found no requirement to introduce:

```text
new Agent framework
new orchestration engine
new scheduler
new broker
new approval engine
new NSL language feature
new Project domain
new identity domain
```

**Finding:** MAJOR CONCLUSION

P9 Foundation can remain materially smaller than P8.

---

# 128. Audit Gap Matrix

| Area | Current Source | P9 Action |
|---|---|---|
| General JobQueue | Implemented | Reuse |
| PostgreSQL concurrent claim | Implemented | Reuse |
| Retry/dead-letter/replay | Implemented | Reuse |
| Worker runner | Implemented | Reuse |
| Worker heartbeat | Implemented | Extend `nex-wa` |
| Service logs/ops | Implemented | Extend service registry |
| AE RuntimeJob | Implemented | Do not use |
| Agent identity IA/CA/PA/EA | Implemented | Reference |
| AgentResult | Implemented | Primary source |
| AE Artifact | Implemented | Primary Human source candidate |
| WC WorkResult | Implemented | Supporting Agent source |
| WC event fan-out | Not implemented | Contract decision |
| WA_PROJECTION target enum | Schema hook only | Contract decision |
| OA Human subject | Implemented | Reference |
| EOS Project | Implemented | Reference |
| EOS ProjectMember | Implemented | Reference |
| WA service | Missing | Implement |
| WA DB | Missing | Implement |
| WorkEvidence | Missing | Implement |
| WorkAsset | Missing | Implement |
| Evidence idempotency | Missing | Implement |
| Supersession | Missing | Implement |
| ContributionCandidate | Missing | Later P9 |
| Human generic WorkResult | Missing | Avoid or defer |
| NSL WA Skills | Missing | Deferred |
| Scheduler | Not needed | Out of scope |
| External broker | Not needed | Deferred |

---

# 129. Key Contract Closure Decisions

The next Contract Closure must resolve at least:

```text
CC-Q01
What is the exact first-source set?
Recommendation: AE_AGENT_RESULT + AE_ARTIFACT,
with WC_WORK_RESULT as supporting lineage.

CC-Q02
What is the exact WA intake trigger?
Direct safe projection, source-ref API, or optional source delivery.

CC-Q03
How is AE WA_PROJECTION used, if at all, without weakening required
WORKSPACE_RESULT / WC_WORK_RESULT delivery?

CC-Q04
What is the canonical WorkEvidence identity?

CC-Q05
What is the WorkAsset v1 granularity?

CC-Q06
Can WorkEvidence and WorkAsset be persisted in one local transaction?

CC-Q07
How are AgentResult, WC WorkResult and Artifact bound to one logical work unit
without double-counting?

CC-Q08
What exact Human evidence path is required in P9 v1?

CC-Q09
What exact EOS Project/ProjectMember safe verification contract is needed?

CC-Q10
What exact OA Human subject verification contract is needed?

CC-Q11
What source classification becomes the WA classification?

CC-Q12
What are WorkEvidence supersession/invalidation semantics?

CC-Q13
What is the minimum query/privacy surface?

CC-Q14
Which common static service registries must add `nex-wa`?

CC-Q15
What exact `WA_EVIDENCE_INGEST` payload is allowed?

CC-Q16
What retry/max-attempt/dead-letter policy is required?

CC-Q17
What is the worker process command/lifecycle contract?

CC-Q18
What is the exact P9.2/P9.3 protected PostgreSQL acceptance?

CC-Q19
How are Frozen Work Asset v2.0 documents reconciled with PAD v1.2 and current source?

CC-Q20
What exact candidate output does Golden C need from P9.5?
```

---

# 130. Recommended Contract Closure Direction

The simplest contract direction is:

```text
Source System
        │
        │ safe exact reference
        ▼
nex-wa-api
        │
        │ validate request / enqueue
        ▼
WA service_jobs
        │
        ▼
nex-wa-evidence-consumer
        │
        ├─ source adapter
        ├─ authoritative source verification
        ├─ actor normalization
        ├─ Project validation
        ├─ source equivalence
        ├─ evidence idempotency
        └─ local transaction
        ▼
WorkEvidence
        │
        ▼
WorkAsset
```

No approval, NSL, delegation, scheduler or external broker is needed.

---

# 131. Recommended Initial Human/Agent Proof

To keep P9 Foundation small:

```text
Human:
AE Artifact owner_actor_ref
→ OA subject validation
→ optional EOS Project relationship
→ WorkEvidence

Agent:
AE AgentResult
→ agent_id / agent_type
→ project/claim lineage
→ WorkEvidence
```

This is enough to prove the HUMAN/AGENT common WA actor model.

---

# 132. Recommended WC Role in P9 Foundation

WC should remain:

```text
authoritative work-coordination source
```

not:

```text
mandatory WA ingress
```

For current CA/PA/EA flows, WC references enhance Agent evidence.

P9 should not route all WA registration through WC Delegation.

---

# 133. Recommended Approval Rule

Freeze:

```text
authoritative system-generated evidence admission
= no Human Approval
```

while preserving:

```text
downstream consequential business decision
= may require Human/Policy confirmation
```

This is consistent with current P8 source architecture.

---

# 134. Recommended NSL Rule

Freeze for P9 Foundation:

```text
NSL is not required.
```

Do not create WA-specific Skill files until after Foundation contracts are
stable and a natural-language WA operation is explicitly needed.

---

# 135. Recommended Golden C Boundary

P9 should stop at:

```text
evidence-backed candidate
```

Golden C begins at:

```text
candidate confirmation/finalization
→ 0.05 MM
→ compensation
→ labor cost
→ management accounting
→ Project P/L
```

---

# 136. Source Audit Exit Criteria

This Source Audit is sufficient to enter Contract Closure when the team accepts:

```text
1. NeX-WA is a new owner-local service.
2. P8 shared JobQueue/worker infrastructure is reused.
3. AE RuntimeJob is not reused.
4. WA evidence intake is background and approval-free.
5. NSL is out of Foundation scope.
6. AE AgentResult is the strongest first Agent source.
7. AE Artifact is the strongest current first Human-source candidate.
8. WC WorkResult is currently Agent-only and should not be treated as Human work.
9. Current WC outbox is not a generic multi-subscriber event bus.
10. WA_PROJECTION is a schema hook, not an implemented delivery path.
11. Source-reference intake and owner verification are preferred for minimal Foundation.
12. WorkEvidence needs independent source idempotency.
13. AgentResult/WorkResult/Artifact lineage must avoid double-counting.
14. WorkAsset granularity remains a Contract Closure decision.
15. ContributionCandidate is later P9, not initial persistence.
16. Frozen Work Asset binary references require explicit reconciliation before freeze.
```

---

# 137. Final Audit Decision

The source audit supports proceeding with P9.

The implementation should remain small.

```text
P8 reusable foundation
────────────────────────────────
JobQueue
WorkerRunner
Heartbeat
Agent identity
AgentResult
Artifact
WorkResult
OA Subject
EOS Project / ProjectMember
        │
        ▼
P9 new minimum
────────────────────────────────
nex-wa service
WA PostgreSQL
WA service_jobs
nex-wa-evidence-consumer
source adapters
WorkEvidence
WorkAsset
source/evidence idempotency
safe queries
        │
        ▼
later P9
────────────────────────────────
ContributionCandidate
HumanEffortCandidate
AgentEffortCandidate
        │
        ▼
Golden C
```

The most important Source Audit conclusion is:

> **NeX-WA Foundation should not be implemented as another workflow engine.
> It should be implemented as a small, owner-local, asynchronous evidence
> service that reuses the Platform's existing JobQueue and worker primitives,
> verifies authoritative source references, and creates immutable,
> idempotent WorkEvidence/WorkAsset records without Human Approval.**
