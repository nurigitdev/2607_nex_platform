# P9 — NeX-WA (Work Asset)
# Software Requirements Specification v1.1

**Document Status:** PRE-IMPLEMENTATION SRS v1.1 / P9-CA01 PASS / P9.2 CODING AUTHORIZED
**Phase:** P9 — NeX-WA / Work Asset Foundation
**Platform:** NeX Platform v2.1
**Predecessor:** P8 CLOSED / P9 Entry Authorized
**Pre-Architecture:** `P9_NeX_WA_Pre_Architecture_Decision_v1.2.md`
**Source Audit:** `P9_NeX_WA_Source_Audit_and_Gap_Analysis_v1.0.md`
**Contract Closure:** `P9_NeX_WA_Contract_Closure_v1.1.md`
**Platform Repository:** `nurigitdev/2607_nex_platform`
**Entry Branch:** `transition/p4-agent-runtime-foundation`
**Entry HEAD:** `c3a1ea907387b67fe7a63407e4d668d13b1be8e7`
**Entry Tree:** `7df03a1ff280baefbda4e56b1ff0e0818ef0bde3`
**Quality Baseline:** Statement ≥ 96%, Branch ≥ 94%
**WA Development DB:** `nex_wa_dev`
**WA Test DB:** `nex_wa_test`
**WA Local API Port:** `8108`
**Revision Note:** v1.1 back-propagates P9-CC-31~34: authoritative AgentResult completion barrier, WC supporting resolution by exact execution lineage, fenced stale-RUNNING recovery, and the Frozen-WA reconciliation gate. It also closes bounded privacy-read scopes, updates traceability/E2E acceptance, and adds a forward-compatibility invariant for future PA Scheduler/Harness execution-authority profiles. P9-CA01 records that gate as PASS and clarifies asset-relative binding roles, PRIMARY binding ownership, and WorkAsset semantic hashing before persistence implementation.
**Date:** 2026-10-27

---

## 1. Purpose

본 SRS는 P9에서 NeX-WA Foundation을 구현하기 위한 기능, 데이터,
API, 보안, 비동기 처리, 신뢰성 및 검증 요구사항을 정의한다.

P9의 canonical flow는 다음과 같다.

```text
AE AgentResult / AE Artifact / WC WorkResult
        │
        │ exact source reference
        ▼
    nex-wa-api
        │
        │ WA_EVIDENCE_INGEST
        ▼
  WA service_jobs
        │
        │ concurrent claim
        ▼
nex-wa-evidence-consumer
        │
        ├─ source verification
        ├─ actor verification
        ├─ project verification
        ├─ source/hash verification
        ├─ idempotency
        └─ source equivalence
        │
        ▼
   WorkEvidence
        │
        ▼
    WorkAsset
```

P9의 핵심 원칙은 다음과 같다.

> **NeX-WA는 workflow engine이 아니라, 기존 authoritative source가
> 증명하는 Human-owned deliverable 및 Agent-executed work를 background로
> 수집하고 검증하여 immutable WorkEvidence/WorkAsset으로 만드는
> owner-local evidence service이다.**

---

## 2. Normative Source Order

P9 구현은 다음 우선순위를 따른다.

```text
1. P8 Final As-Built / current executable P8 source
2. P9 Contract Closure v1.1
3. this P9 SRS v1.1
4. P9 Pre-Architecture Decision v1.2
5. P9 Source Audit v1.0
6. earlier legacy/frozen Work Asset references
7. implementation convenience
```

구현 편의를 이유로 상위 contract의 의미를 변경해서는 안 된다.

Legacy/Frozen Work Asset 문서 내부 내용이 후속 materialization에서 본
SRS와 실제로 충돌하는 경우에는 silent merge가 아니라:

```text
P9 Controlled Amendment
```

가 필요하다.

### P9-GATE-001 — Frozen WA Reconciliation Before P9.2 Coding

P9 SRS 및 Implementation Slice Plan 작성은 본 문서를 기준으로 진행할 수 있다.

그러나 실제 P9.2 production domain coding 시작 전에는 다음 Frozen/reference
artifact를 materialize하여 현재 P8/P9 기준선과 reconcile해야 한다.

```text
23_NeX_Work_Asset_Human_Effort_and_Labor_Allocation_Design_v2.0.docx
23_NeX_Work_Asset_Human_Effort_and_Labor_Allocation_Implementation_Contracts_v2.0.zip
```

Reconciliation 결과는 최소 다음 중 하나로 분류한다.

```text
COMPATIBLE
ADDITIVE / INCORPORATE
CONFLICT / CONTROLLED AMENDMENT REQUIRED
NOT APPLICABLE TO P9 FOUNDATION
```

비교 기준은 다음과 같다.

```text
P8 Final As-Built v1.2 + merged P8-DEMO baseline
P9 Pre-Architecture Decision v1.2
P9 Source Audit v1.0
P9 Contract Closure v1.1
this SRS v1.1
```

다음이 성립한다.

```text
P9 SRS / Slice Plan
= MAY PROCEED

P9.2 production domain coding
= BLOCKED until reconciliation PASS
```

materialized Frozen/reference semantics가 ownership/SoR, identity, approval,
result-publication completion, WorkEvidence 또는 WorkAsset semantics와 실제
충돌하면 구현을 시작하지 않고 P9 Controlled Amendment를 수행한다.

P9-CA01 결과:

```text
reconciliation record = P9_CA01_Frozen_WA_Reconciliation_and_Coding_Entry_Gate_v1.0.md
materialization integrity = PASS
unresolved material conflict = 0
P9.2 production domain coding = AUTHORIZED
```

---

## 3. Scope

P9 Foundation은 다음을 포함한다.

```text
nex-wa first-class service
nex-wa-api
nex-wa-evidence-consumer

nex_wa_dev / nex_wa_test PostgreSQL

shared service_jobs reuse
shared WorkerRunner reuse
shared WorkerHeartbeat reuse

WA_EVIDENCE_INGEST

AE AgentResult source projection
AE Artifact source projection
WC WorkResult supporting projection

source notification / intake
source verification

HUMAN / AGENT actor normalization
IA / CA / PA / EA snapshot

Project attribution
OA Human verification
EOS Project / ProjectMember verification

WorkEvidence
WorkAsset
WorkAsset↔Evidence binding

source/evidence idempotency
source equivalence
supersession/invalidation

stale RUNNING Job recovery
retry / dead-letter / replay
bounded reconciliation/backfill

bounded service read APIs
privacy-safe projection
protected PostgreSQL E2E
```

---

## 4. Out of Scope

P9 Foundation은 다음을 구현하지 않는다.

```text
general scheduler
resource scheduling
automatic staffing
employee performance rating
universal productivity score
payroll
salary
bonus decision
Project monetary labor cost
Management Voucher
Project P/L
Agent monetary cost

NSL source / NSO / NSP
WA Skill Pack
Controlled WRITE
Human Approval for ordinary evidence

Kafka
RabbitMQ
NATS
Redis Streams

direct cross-service database access
public/browser WA mutation UI
```

Contribution Candidate의 persistence/formula는 P9.5 이전에는 범위 밖이다.

---

# 5. Service Ownership

## P9-FR-001 — First-Class NeX-WA Service

Platform SHALL add:

```text
service_id = nex-wa
```

as a first-class service identity.

---

## P9-FR-002 — WA-Owned Processes

WA SHALL initially own exactly:

```text
nex-wa-api
nex-wa-evidence-consumer
```

No third scheduler/dispatcher process is required.

---

## P9-FR-003 — WA-Owned State

NeX-WA SHALL own:

```text
WorkEvidence
WorkAsset
WorkAsset↔Evidence binding
WA source admission
WA JobQueue
WA worker state/heartbeat
WA evidence lifecycle
WA query projection
```

---

## P9-FR-004 — External Authority Preservation

WA SHALL NOT become SoR for:

```text
Human Principal     -> OA
Agent identity      -> AE
AgentExecution      -> AE
WorkItem / Claim    -> WC
Project             -> EOS
ProjectMember       -> EOS
Artifact bytes      -> AE/Object Storage
Compensation        -> Golden C/EOS
```

---

# 6. Runtime and Deployment Requirements

## P9-RUN-001 — API Port

Local/runtime HTTP port for:

```text
nex-wa-api
```

SHALL be:

```text
8108
```

This follows current Platform sequence:

```text
8106 = WC
8107 = EOS
8108 = WA
```

Staging/production MAY terminate TLS at the Platform ingress while preserving
the internal process port.

---

## P9-RUN-002 — Service Endpoint Environment

Platform SHALL define:

```text
NEX_WA_BASE_URL
```

Default local value:

```text
http://127.0.0.1:8108
```

Staging target MAY use:

```text
https://wa.nex-staging.test:8443
```

consistent with the existing staging TLS pattern.

---

## P9-RUN-003 — Deployment Artifact

Platform SHALL add:

```text
artifact_id = nex-wa-runtime
owner       = nex-wa
kind        = python-service
```

source roots SHALL include:

```text
services/_shared/nex_runtime
services/nex-wa/nex_wa
```

---

## P9-RUN-004 — Process Bindings

Deployment catalog SHALL bind:

```text
nex-wa-api
  -> nex-wa-runtime / api

nex-wa-evidence-consumer
  -> nex-wa-runtime / evidence-consumer
```

---

## P9-RUN-005 — Container Security

WA runtime containers SHALL follow current P8 release hardening:

```text
non-root
read-only filesystem where applicable
tmpfs for temporary writes
cap_drop ALL
no-new-privileges
managed secrets
managed TLS trust
no host port publication in protected compose
```

---

# 7. PostgreSQL Requirements

## P9-DB-001 — WA Development Database

P9 SHALL use:

```text
nex_wa_dev
```

for development runtime.

---

## P9-DB-002 — WA Test Database

P9 SHALL use:

```text
nex_wa_test
```

for protected PostgreSQL tests.

Tests SHALL reset/initialize the test DB deterministically before database
acceptance suites.

---

## P9-DB-003 — WA Database Role

Expected database role:

```text
nex_wa_user
```

WA SHALL not share an owner credential with AE/WC/OA/EOS.

---

## P9-DB-004 — No Cross-Database FK

WA tables SHALL NOT define foreign keys to:

```text
AE DB
WC DB
OA DB
EOS DB
```

External identities are stored as stable refs only.

---

## P9-DB-005 — Required Foundation Tables

P9.2 SHALL create at least:

```text
schema_migrations
service_jobs
service_worker_heartbeats
wa_work_evidence
wa_work_asset
wa_work_asset_evidence
```

---

# 8. Shared JobQueue Requirements

## P9-JOB-001 — Shared JobQueue Reuse

WA SHALL reuse:

```text
nex_runtime.jobs.JobQueue
nex_runtime.jobs.SqlAlchemyJobQueue
```

and SHALL NOT create a second queue abstraction.

---

## P9-JOB-002 — Job Schema

WA SHALL use:

```text
common_job.v1
```

without semantic fork.

---

## P9-JOB-003 — Job Type

Initial Job type SHALL be exactly:

```text
WA_EVIDENCE_INGEST
```

---

## P9-JOB-004 — Job States

WA SHALL use only:

```text
QUEUED
RUNNING
SUCCEEDED
FAILED
CANCELLED
```

for Foundation Job state.

---

## P9-JOB-005 — Reference-Only Payload

`WA_EVIDENCE_INGEST` payload SHALL contain only bounded references/hashes.

Required:

```text
source_type
source_ref
source_revision_ref
source_hash
```

The payload SHALL NOT contain raw business content.

---

## P9-JOB-006 — Deterministic Job Identity

`job_id` SHALL be deterministic UUIDv5 from:

```text
namespace = nex-wa-evidence-ingest-v1
tenant_id
source_type
source_ref
source_revision_ref
```

Equivalent requests SHALL derive the same Job ID.

---

## P9-JOB-007 — Queue Idempotency Key

`idempotency_key` SHALL be:

```text
sha256(
  canonical_json(
    tenant_id,
    source_type,
    source_ref,
    source_revision_ref
  )
)
```

The source hash SHALL NOT be part of the identity key.

This permits semantic conflict detection when the same source revision is
reused with a different hash.

---

## P9-JOB-008 — Idempotent Payload Consistency

When an existing Job is found for the same source identity, WA intake SHALL
compare:

```text
source_hash
source_type
source_ref
source_revision_ref
tenant_id
```

If any semantic value differs:

```text
WA_SOURCE_IDEMPOTENCY_CONFLICT
```

SHALL be returned.

---

## P9-JOB-009 — Retry Policy

Default WA Job retry policy SHALL be:

```text
max_attempts = 5
initial_delay_seconds = 30
max_delay_seconds = 900
backoff_multiplier = 2.0
```

---

## P9-JOB-010 — Concurrent Claim

PostgreSQL worker claim SHALL use existing:

```text
FOR UPDATE SKIP LOCKED
```

semantics.

---

## P9-JOB-011 — Horizontal Worker Scaling

Multiple WA consumers SHALL be allowed to run concurrently without duplicate
semantic processing.

---

## P9-JOB-012 — No External Broker

P9 Foundation SHALL NOT require an external broker.

---

# 9. Stale RUNNING Recovery

## P9-REL-001 — Recovery Need

WA SHALL handle a process crash after a Job transitions to:

```text
RUNNING
```

but before it reaches a terminal state.

---

## P9-REL-002 — Stale Timeout

Default stale Job threshold SHALL be:

```text
300 seconds
```

Environment:

```text
NEX_WA_STALE_JOB_SECONDS=300
```

Allowed configuration range:

```text
60..3600 seconds
```

---

## P9-REL-003 — Heartbeat Condition

A RUNNING Job SHALL be eligible for stale recovery only when:

```text
locked_at < now - stale_threshold
```

AND the owning worker heartbeat is missing or stale.

The current shared worker heartbeat stale threshold MAY remain 60 seconds.

---

## P9-REL-004 — Fenced Stale Job Requeue

If attempts remain, stale recovery SHALL use one compare-and-set transition:

```text
RUNNING stale
→ QUEUED
```

The update SHALL match at least:

```text
job_id
expected status = RUNNING
expected locked_by
expected locked_at
```

or an equivalent versioned claim token.

On success:

```text
locked_by = null
locked_at = null
available_at = recovery_time
```

with a bounded recovery reason.

A recovery update that does not match the expected ownership state SHALL make
no mutation.

---

## P9-REL-005 — Stale Job Dead-Letter

If attempts are exhausted:

```text
RUNNING stale
→ FAILED
error.dead_lettered = true
```

---

## P9-REL-006 — Recovery Idempotency

Stale recovery SHALL rely on independent WorkEvidence idempotency and SHALL
never duplicate semantic evidence.

Evidence idempotency does not replace worker-ownership fencing.

---

## P9-REL-007 — Recovery Invocation

Foundation SHALL support recovery through:

```text
worker startup recovery probe
```

and MAY expose a protected operator command for bounded recovery.

It SHALL NOT require a scheduler.

---

## P9-REL-008 — WA Job Claim Fence

A successfully claimed WA Job SHALL carry a settlement fence derived from the
exact claim state, using at least:

```text
job_id
locked_by
locked_at
```

or an equivalent persisted claim-generation/token representation.

WA-specific complete/fail/retry settlement SHALL compare the current persisted
claim ownership before changing Job state.

---

## P9-REL-009 — Stale Worker Settlement Rejection

After a stale Job is successfully recovered/requeued, the previous worker SHALL
lose settlement authority.

If the stale worker later attempts:

```text
complete
fail
retry
dead-letter
```

with the former claim fence, the operation SHALL fail without mutation using a
typed condition such as:

```text
WA_JOB_OWNERSHIP_LOST
retryable = false for that stale settlement attempt
```

This requirement MAY be implemented through a backward-compatible shared
JobQueue ownership-CAS extension or a WA-specific composition layer, but SHALL
NOT bypass the common JobQueue persistence model.

---

# 10. Worker Runtime

## P9-WRK-001 — Worker Type

Consumer worker type SHALL be:

```text
wa.evidence_consumer
```

---

## P9-WRK-002 — Worker ID

Each process instance SHALL have a unique:

```text
NEX_WA_WORKER_ID
```

Example:

```text
wa-evidence-consumer-1
```

---

## P9-WRK-003 — Shared WorkerRunner

The consumer SHOULD compose:

```text
WorkerRunnerConfig
run_worker_once / run_worker_batch
WorkerHeartbeatEmitter
ServiceLogEmitter
```

rather than reimplementing lifecycle primitives.

---

## P9-WRK-004 — Worker Heartbeat

Worker SHALL emit:

```text
STARTING
IDLE
BUSY
STOPPING
STOPPED
ERROR
```

using:

```text
service_id = nex-wa
```

---

## P9-WRK-005 — Worker Graceful Shutdown

SIGTERM/SIGINT handling SHALL stop new claims and allow the current bounded
operation to finish or fail safely.

---

# 11. Evidence Intake API

## P9-API-001 — Intake Route

WA SHALL expose:

```text
POST /internal/v1/evidence-intake
```

---

## P9-API-002 — Intake Request Schema

Request schema SHALL be:

```text
wa_evidence_intake_request.v1
```

Minimum fields:

```json
{
  "schema_version": "wa_evidence_intake_request.v1",
  "tenant_id": "...",
  "source_type": "AE_AGENT_RESULT",
  "source_ref": "...",
  "source_revision_ref": "...",
  "source_hash": "sha256:...",
  "occurred_at": "...",
  "correlation_id": "..."
}
```

`occurred_at` and `correlation_id` are bounded notification metadata only;
the worker SHALL re-read authoritative source values.

---

## P9-API-003 — Initial External Intake Source Types

Initial external `POST /internal/v1/evidence-intake` source types are exactly:

```text
AE_AGENT_RESULT
AE_ARTIFACT
```

`WC_WORK_RESULT` remains a valid WA supporting evidence source type, but it is
NOT an independent mandatory external intake type in the initial Foundation.

For background Agent work, WC WorkResult is resolved by `nex-wa` through the
exact AgentExecution / Claim lineage while processing `AE_AGENT_RESULT`.

---

## P9-API-004 — Intake Response

Successful admission SHALL return HTTP:

```text
202 Accepted
```

with:

```text
wa_evidence_intake_admission.v1
```

including:

```text
job_id
job_type
status
source_type
source_ref
source_revision_ref
idempotent_reuse
request_id
trace_id
```

---

## P9-API-005 — Intake Is Not Evidence Acceptance

HTTP 202 means:

```text
source inspection accepted
```

not:

```text
evidence admitted as true
```

Evidence truth is established by worker verification.

---

# 12. Intake Authentication and Authorization

## P9-SEC-001 — WA Audience

Inbound WA service token SHALL use:

```text
audience = nex-wa
```

---

## P9-SEC-002 — Default Service Scope

Every WA internal caller SHALL require the Platform:

```text
DEFAULT_SERVICE_SCOPE
```

---

## P9-SEC-003 — Intake Scope

WA evidence intake SHALL additionally require:

```text
work:evidence:ingest
```

---

## P9-SEC-004 — Allowed Intake Services

Initial allowed source-notification service IDs:

```text
nex-ae-api
```

`nex-wc` is not required to push an independent WA intake notification in the
initial Foundation. WA calls WC as an authoritative supporting-source owner.

No browser/user token is accepted by `/internal/v1/evidence-intake`.

---

## P9-SEC-005 — Basic Read Scope

Basic WorkAsset reads and bounded aggregate/list projections SHALL require:

```text
work:evidence:read
```

in addition to the default service scope.

---

## P9-SEC-006 — Detailed Evidence Scope

Individual WorkEvidence detail and WorkAsset evidence-lineage reads SHALL
additionally require:

```text
work:evidence:detail:read
```

This scope authorizes bounded refs/hashes and evidence metadata only. It does
not authorize raw source content.

---

## P9-SEC-007 — Evidence Audit Scope

Supersession/invalidation, source-conflict, replay lineage and bounded audit
provenance SHALL additionally require:

```text
work:evidence:audit:read
```

A caller with only `work:evidence:read` SHALL receive a redacted/denied
projection rather than detailed Human activity lineage.

---

# 13. Source Notification Requirements

## P9-FR-010 — Post-Completion AgentResult Notification

AE SHOULD notify WA only after the authoritative result-publication completion
barrier has closed.

Required state:

```text
AgentResult.status = SUCCEEDED | PARTIAL
AgentExecution.state = SUCCEEDED
required ResultDelivery.state = ACKNOWLEDGED
```

The required delivery target is:

```text
IA           -> WORKSPACE_RESULT
CA / PA / EA -> WC_WORK_RESULT
```

AgentResult persistence by itself is not a sufficient WA post-work notification
point.

WA notification failure SHALL NOT roll back AgentResult, ResultDelivery ACK, or
AgentExecution completion.

---

## P9-FR-011 — Post-READY Artifact Notification

When an Artifact version reaches:

```text
READY
```

AE SHOULD notify WA with exact Artifact/version/hash references.

WA notification failure SHALL NOT roll back Artifact rendering.

---

## P9-FR-012 — WC WorkResult Supporting Resolution

The initial Foundation SHALL NOT require an independent WC→WA WorkResult
notification.

For background Agent work, `nex-wa-evidence-consumer` SHALL resolve the related
WC WorkResult through the exact AgentExecution / Claim lineage after verifying
the primary AE AgentResult completion barrier.

WC remains the authoritative source owner; WA retrieves a bounded supporting
projection.

No new WC multi-subscriber event bus is required for this Foundation path.

---

## P9-FR-013 — Notification Failure

Source service SHALL:

```text
preserve source success
record bounded operational failure
allow later reconciliation/backfill
```

when WA is unavailable.

---

# 14. AE AgentResult Source Projection

## P9-API-010 — AgentResult Projection Route

AE SHALL expose:

```text
GET /internal/v1/wa-sources/agent-results/{result_id}
```

---

## P9-SEC-010 — AgentResult Projection Caller

Only:

```text
nex-wa
```

with:

```text
DEFAULT_SERVICE_SCOPE
work:source:read
```

SHALL be admitted.

---

## P9-API-011 — AgentResult Projection Schema

Projection schema SHALL be:

```text
wa_agent_result_source_projection.v1
```

and contain at least:

```text
tenant_id
result_id
agent_execution_id
agent_id
agent_type
project_id
status
result_hash
artifact_refs
evidence_refs
business_refs
source_work_item_ref
source_claim_ref
source_claim_generation
source_assignment_ref
created_at

agent_execution_state
required_delivery_target_type
required_delivery_state
required_delivery_ref
delivery_acknowledged_at
```

`required_delivery_ref` and `delivery_acknowledged_at` MAY be nullable only
where the authoritative source semantics permit it; positive post-work
admission requires an ACKNOWLEDGED required delivery.

No raw result text is returned.

---

## P9-FR-020 — Positive AgentResult Completion Barrier

`AgentResult.status` alone SHALL NOT create positive WorkEvidence.

Positive `AE_AGENT_RESULT` admission requires all of:

```text
AgentResult.status = SUCCEEDED | PARTIAL
AgentExecution.state = SUCCEEDED
required ResultDelivery.state = ACKNOWLEDGED
```

The required delivery target SHALL match the Agent type:

```text
IA           -> WORKSPACE_RESULT
CA / PA / EA -> WC_WORK_RESULT
```

For `CA / PA / EA`, current WorkItem / Claim / claim-generation / Assignment
lineage SHALL also be preserved and verified.

If AgentResult exists but the required delivery is not ACKNOWLEDGED:

```text
WA_AGENT_RESULT_NOT_COMPLETE
retryable = true
```

WA SHALL NOT create positive post-work WorkEvidence yet.

---

## P9-FR-021 — Non-Positive AgentResult

```text
BLOCKED
FAILED
CANCELLED
```

SHALL NOT produce positive contribution evidence.

They MAY be ignored by Foundation after source validation.

---

# 15. Agent Identity and Project Requirements

## P9-FR-022 — Agent Actor

Agent evidence SHALL normalize to:

```text
actor_type = AGENT
actor_ref  = agent_id
```

---

## P9-FR-023 — Agent Type Snapshot

Agent evidence SHALL preserve:

```text
IA
CA
PA
EA
```

as:

```text
agent_type_snapshot
```

---

## P9-FR-024 — Background Agent Project

For:

```text
CA
PA
EA
```

source projection SHALL contain:

```text
project_id
source_work_item_ref
source_claim_ref
source_claim_generation
source_assignment_ref
```

Missing required lineage SHALL fail admission.

---

## P9-FR-025 — IA Project Neutrality

For IA:

```text
project_ref = null
```

unless another authoritative Project reference exists.

Free text SHALL never establish Project authority.

---

## P9-FR-026 — Future Agent Execution Authority Compatibility

NeX-WA SHALL NOT require WC lineage as an intrinsic property of every future
Agent WorkAsset.

WA SHALL require that NeX-AE can prove an authoritative execution-authority
profile and an authoritative completion-evidence profile for the AgentExecution
being admitted.

P9 v1 admits only the current authority profiles:

```text
IA
execution trigger / authority = PROMPT
completion evidence           = WORKSPACE_RESULT ACKNOWLEDGED

CA / PA / EA
execution trigger / authority = CLAIMED_WORKITEM
completion evidence           = WC_WORK_RESULT ACKNOWLEDGED
```

Accordingly, current `CA / PA / EA` admission still requires the existing
Project / WorkItem / Claim / ClaimGeneration / Assignment lineage.

However, WC Claim lineage SHALL NOT be encoded as the permanent semantic
definition of all future Agent work in NeX-WA.

A future authority profile such as:

```text
AUTONOMOUS_HARNESS
AGENT_INITIATED
or equivalent
```

MAY be admitted only after a separate Controlled Amendment closes at least:

```text
execution authorization source
Project scope authority
resource / model / tool limits
recurrence / self-trigger controls
kill-switch / governance
completion barrier
audit lineage
```

Until such amendment closes, an unknown autonomous execution-authority profile
SHALL fail closed.

This requirement preserves P9 Foundation scope while allowing future PA
Scheduler/Harness evolution without redefining WorkEvidence or WorkAsset
identity.

---

# 16. AE Artifact Source Projection

## P9-API-020 — Artifact Projection Route

AE SHALL expose:

```text
GET /internal/v1/wa-sources/artifacts/{artifact_id}/versions/{artifact_version_id}
```

---

## P9-API-021 — Artifact Projection Schema

Projection schema SHALL be:

```text
wa_artifact_source_projection.v1
```

with at least:

```text
tenant_id
artifact_id
artifact_version_id
artifact_status
owner_actor_ref
workspace_ref
source_content_hash
artifact_content_hash
created_at
classification
producer_execution_ref
```

`producer_execution_ref` MAY be null if source cannot prove an Agent producer.

---

## P9-FR-030 — Artifact Status

Only:

```text
READY
```

Artifact versions SHALL be admitted as normal positive WorkEvidence.

---

## P9-FR-031 — Artifact Version Identity

Artifact source identity SHALL use:

```text
source_ref          = artifact_id
source_revision_ref = artifact_version_id
source_hash         = artifact_content_hash
```

---

# 17. Human Actor Requirements

## P9-FR-032 — Human Actor Type

A verified user-owned Artifact SHALL normalize to:

```text
actor_type = HUMAN
```

---

## P9-FR-033 — Canonical Human Identity

Canonical Human actor reference SHALL be:

```text
OA subject_id
```

not display name or employee number.

---

## P9-FR-034 — Human Owner Resolution

AE Artifact source projection SHOULD expose an OA-subject-compatible owner
reference.

If WA cannot verify the owner as an active tenant subject:

```text
Human evidence admission fails closed
```

---

## P9-FR-035 — Artifact Ownership Semantics

Artifact ownership proves only:

```text
ownership/responsibility
deliverable association
Artifact existence
```

It SHALL NOT prove Human effort quantity.

---

## P9-FR-036 — Human Evidence Kind

Initial Human Artifact evidence kind SHALL be:

```text
OWNERSHIP_OR_DELIVERABLE_EVIDENCE
```

---

# 18. OA Subject Verification

## P9-API-030 — OA Subject Verify Route

OA SHALL expose:

```text
POST /internal/v1/identity/subjects:verify-batch
```

---

## P9-SEC-030 — OA Subject Verify Scope

Caller `nex-wa` SHALL require:

```text
DEFAULT_SERVICE_SCOPE
identity:subject:verify
```

---

## P9-API-031 — OA Subject Verify Request

Maximum batch size:

```text
50
```

Request SHALL contain:

```text
tenant_id
subject_ids[]
```

---

## P9-API-032 — OA Subject Verify Result

Per subject result SHALL distinguish:

```text
VERIFIED
SUBJECT_NOT_FOUND
SUBJECT_INACTIVE
TENANT_MEMBERSHIP_MISSING
```

A verified result SHALL include bounded revision evidence.

---

# 19. WC WorkResult Supporting Projection

## P9-API-040 — WorkResult Projection Route

WC SHALL expose:

```text
GET /internal/v1/wa-sources/work-results/{result_id}
```

---

## P9-SEC-040 — WorkResult Projection Scope

Caller `nex-wa` SHALL require:

```text
DEFAULT_SERVICE_SCOPE
work:source:read
```

---

## P9-API-041 — WorkResult Projection Schema

Projection SHALL contain only:

```text
tenant_id
result_id
work_item_id
revision_no
result_hash
source_execution_ref
claim_id
claim_generation
assignment_id
submitted_agent_id
submitted_at
```

No unbounded `result_payload` is returned.

---

## P9-API-042 — WorkResult By-Execution Resolution Route

For the canonical background Agent flow, WC SHALL expose an exact,
tenant-scoped supporting-source lookup equivalent to:

```text
GET /internal/v1/wa-sources/work-results/by-execution/{agent_execution_id}
```

The lookup SHALL validate the current bounded lineage carried by the primary
AgentResult, including the applicable:

```text
tenant_id
source_execution_ref
claim_id
claim_generation
assignment_id
submitted_agent_id
```

and return at most the canonical matching WorkResult projection for the
completed Agent execution.

A lineage mismatch SHALL fail closed.

For correction-aware resolution, `work_item_id` is the stable logical
`WC_WORK_RESULT` source reference and `result_id` is its immutable source
revision reference. When a previous revision exists, the projection MAY also
return the bounded pair `supersedes_result_id` and `supersedes_revision_no`.
Both values SHALL be present together and SHALL describe the immediately prior
revision in the same execution, claim, assignment, and submitted-Agent lineage.

---

## P9-FR-040 — Supporting-Only Semantics

`WC_WORK_RESULT` SHALL be attached with:

```text
binding_role = SUPPORTING
```

in Foundation.

It SHALL NOT independently create Human evidence or a primary WorkAsset.

For the initial Foundation, it is resolved from the primary
`AE_AGENT_RESULT` lineage rather than being a required independent intake Job.

---

# 20. EOS Project Verification

## P9-API-050 — Project Verify Route

EOS SHALL expose:

```text
POST /internal/v1/projects:verify-batch
```

for exact Project identity validation.

---

## P9-SEC-050 — Project Verify Scope

Caller `nex-wa` SHALL require:

```text
DEFAULT_SERVICE_SCOPE
project:verify
```

---

## P9-API-051 — Project Verify Result

Result SHALL distinguish at least:

```text
VERIFIED
PROJECT_NOT_FOUND
PROJECT_INACTIVE
TENANT_MISMATCH
```

---

## P9-API-052 — Historical Membership Verify Route

EOS SHALL expose:

```text
POST /internal/v1/project-memberships:verify-at
```

Input:

```text
tenant_id
project_id
subject_id
occurred_at
```

---

## P9-API-053 — Historical Membership Result

Successful result SHALL include:

```text
membership_valid = true
project_membership_id
member_role
version
valid_from
valid_to
verification_evidence_hash
```

---

# 21. WorkEvidence Data Requirements

## P9-DB-010 — WorkEvidence Table

`wa_work_evidence` SHALL contain at least:

```text
tenant_id                TEXT/VARCHAR NOT NULL
work_evidence_id         UUID NOT NULL

source_owner             VARCHAR NOT NULL
source_type              VARCHAR NOT NULL
source_ref               VARCHAR NOT NULL
source_revision_ref      VARCHAR NOT NULL
source_hash              VARCHAR NOT NULL

evidence_kind            VARCHAR NOT NULL

actor_type               VARCHAR NOT NULL
actor_ref                VARCHAR NOT NULL
agent_type_snapshot      VARCHAR NULL

project_ref              UUID NULL

occurred_at              TIMESTAMPTZ NOT NULL
observed_at              TIMESTAMPTZ NOT NULL

classification           VARCHAR NOT NULL

evidence_status          VARCHAR NOT NULL
evidence_hash            VARCHAR NOT NULL

supersedes_evidence_id   UUID NULL

created_at               TIMESTAMPTZ NOT NULL
```

---

## P9-DB-011 — WorkEvidence Primary Key

Primary key SHALL be:

```text
(tenant_id, work_evidence_id)
```

---

## P9-DB-012 — Source Uniqueness

WA SHALL enforce unique:

```text
(tenant_id, source_type, source_ref, source_revision_ref)
```

for one semantic source revision.

---

## P9-DB-013 — WorkEvidence ID

`work_evidence_id` SHALL be deterministic UUIDv5 from:

```text
tenant_id
source_type
source_ref
source_revision_ref
```

---

## P9-DB-014 — Source Hash Format

`source_hash` SHALL use:

```text
sha256:<64 lowercase hex>
```

---

## P9-DB-015 — Evidence Hash Format

`evidence_hash` SHALL use the same SHA-256 reference format.

---

## P9-DB-016 — Actor Type Check

Allowed:

```text
HUMAN
AGENT
```

---

## P9-DB-017 — Agent Type Snapshot Check

Nullable; when non-null:

```text
IA
CA
PA
EA
```

---

## P9-DB-018 — Evidence Role Ownership

`wa_work_evidence` SHALL NOT persist a global `evidence_role`.

`PRIMARY` / `SUPPORTING` is an asset-relative relationship and SHALL exist
only as `wa_work_asset_evidence.binding_role`.

---

## P9-DB-019 — Evidence Status Check

Allowed:

```text
ACTIVE
SUPERSEDED
INVALIDATED
```

---

## P9-DB-020 — Supersession Integrity

`supersedes_evidence_id` SHALL NOT reference the same evidence ID.

Cross-tenant supersession is forbidden.

---

# 22. WorkEvidence Semantic Hash

## P9-FR-050 — Evidence Hash Projection

`evidence_hash` SHALL bind:

```text
tenant_id
source_owner
source_type
source_ref
source_revision_ref
source_hash
evidence_kind
actor_type
actor_ref
agent_type_snapshot
project_ref
occurred_at
classification
supersedes_evidence_id
```

using canonical JSON and SHA-256.

---

## P9-FR-051 — Same Identity Same Hash

Same source identity + same source hash SHALL reuse existing evidence.

---

## P9-FR-052 — Same Identity Different Hash

Same source identity + different source hash SHALL fail:

```text
WA_SOURCE_IDEMPOTENCY_CONFLICT
```

No overwrite is allowed.

---

# 23. WorkAsset Data Requirements

## P9-DB-030 — WorkAsset Table

`wa_work_asset` SHALL contain at least:

```text
tenant_id
work_asset_id

asset_type

actor_type
actor_ref
agent_type_snapshot

project_ref

occurred_at
classification

asset_status
asset_hash
version

created_at
updated_at
```

---

## P9-DB-031 — WorkAsset Types

Initial allowed types:

```text
AGENT_EXECUTION_RESULT
HUMAN_OWNED_ARTIFACT
```

---

## P9-DB-032 — WorkAsset Status

Allowed:

```text
ACTIVE
SUPERSEDED
INVALIDATED
```

---

## P9-DB-033 — Agent WorkAsset Identity

For `AGENT_EXECUTION_RESULT`, deterministic asset identity SHALL bind:

```text
tenant_id
agent_execution_id
```

---

## P9-DB-034 — Human Artifact WorkAsset Identity

For `HUMAN_OWNED_ARTIFACT`, deterministic asset identity SHALL bind:

```text
tenant_id
artifact_id
artifact_version_id
```

---

## P9-DB-035 — Asset Version

`version` SHALL be positive integer and increment on material projection change.

---

## P9-FR-053 — WorkAsset Hash Projection

`asset_hash` SHALL bind canonical JSON containing:

```text
tenant_id
work_asset_id
asset_type
actor_type
actor_ref
agent_type_snapshot
project_ref
occurred_at
classification
asset_status
bindings[] sorted by binding_role then work_evidence_id
  - work_evidence_id
  - binding_role
```

`created_at`, `updated_at`, `version`, and `asset_hash` itself SHALL NOT be part
of the semantic hash projection.

---

## P9-FR-054 — WorkAsset Version Stability

A material asset or binding change SHALL recompute `asset_hash` and increment
`version` exactly once in the same local unit of work. An exact semantic replay
SHALL change neither the hash nor the version.

---

# 24. WorkAsset↔Evidence Binding

## P9-DB-040 — Binding Table

`wa_work_asset_evidence` SHALL contain:

```text
tenant_id
work_asset_id
work_evidence_id
binding_role
created_at
```

---

## P9-DB-041 — Binding Roles

Allowed:

```text
PRIMARY
SUPPORTING
```

`binding_role` is the sole source of truth for this relationship.

---

## P9-DB-042 — One Primary Evidence

Every ACTIVE WorkAsset SHALL have exactly one PRIMARY binding.

`wa_work_asset` SHALL NOT duplicate the relationship in a
`primary_evidence_id` column. The ACTIVE WorkAsset and PRIMARY binding SHALL be
created atomically; the database/repository boundary SHALL enforce at most one
PRIMARY binding and the domain transaction SHALL reject zero-primary ACTIVE
state.

---

## P9-DB-043 — Binding Uniqueness

Unique:

```text
(tenant_id, work_asset_id, work_evidence_id)
```

---

# 25. Source Equivalence and Double-Counting

## P9-FR-060 — AgentResult Primary

For background Agent work:

```text
AE AgentResult
```

is PRIMARY evidence.

---

## P9-FR-061 — WC WorkResult Equivalence

When:

```text
AgentResult.agent_execution_id
==
WC WorkResult.source_execution_ref
```

and tenant/Agent/claim lineage matches:

```text
WC WorkResult
```

SHALL attach to the same WorkAsset as SUPPORTING evidence.

---

## P9-FR-062 — No Duplicate Agent Asset

Equivalent AgentResult and WorkResult SHALL NOT create two Agent
WorkAssets.

---

## P9-FR-063 — Artifact Supporting Binding

If AgentResult references an Artifact and the Artifact can be proven to belong
to that execution, Artifact evidence MAY bind as SUPPORTING evidence to the
Agent WorkAsset.

---

## P9-FR-064 — Human Ownership vs Agent Production

A Human owner of an Agent-produced Artifact SHALL NOT automatically receive
Human effort credit.

Ownership and production evidence SHALL remain semantically distinct.

---

## P9-FR-065 — Supporting Resolution Cannot Create Primary

In the initial Foundation, WC WorkResult is resolved while processing the
completed primary AgentResult.

The consumer SHALL:

```text
1. verify AgentResult completion barrier
2. create/reuse AgentResult WorkEvidence
3. resolve WC WorkResult by exact execution/claim lineage
4. create/reuse WorkResult WorkEvidence
5. bind AgentResult as PRIMARY and WorkResult as SUPPORTING to the same Agent WorkAsset
```

If WC is temporarily unavailable, the AgentResult intake Job is retryable.

If WC returns a lineage mismatch or conflicting semantic result, admission
fails closed.

WC WorkResult SHALL never create a second primary Agent WorkAsset.

---

## P9-FR-066 — Asset-Relative Evidence Role

One immutable WorkEvidence MAY bind to more than one WorkAsset only when exact
authoritative lineage proves each relationship. Its `binding_role` MAY differ
per WorkAsset. Rebinding SHALL NOT change the evidence actor, source identity,
or semantic hash, and SHALL NOT create Human effort credit.

---

# 26. Local Transaction Requirements

## P9-REL-010 — WA Local Unit of Work

One successful intake handler SHOULD commit in one local PostgreSQL
transaction:

```text
WorkEvidence create/reuse
WorkAsset create/update
WorkAsset↔Evidence binding
```

---

## P9-REL-011 — Job Completion Ordering

Job SHALL become:

```text
SUCCEEDED
```

only after the WA local transaction commits.

---

## P9-REL-012 — Crash After Commit

If local commit succeeds and process crashes before Job completion, retry SHALL
reuse existing evidence/asset and complete the Job.

---

# 27. Classification Requirements

## P9-SEC-060 — Classification Vocabulary

P9 WA projection SHALL support:

```text
INTERNAL
CONFIDENTIAL
RESTRICTED
```

---

## P9-SEC-061 — No Downgrade

WA classification SHALL never be less restrictive than authoritative source
classification.

---

## P9-SEC-062 — Missing Classification Defaults

If a current source has no explicit compatible classification, initial P9
mapping SHALL default to:

```text
CONFIDENTIAL
```

for:

```text
AE_AGENT_RESULT
AE_ARTIFACT
WC_WORK_RESULT
```

A source explicitly marked `RESTRICTED` remains `RESTRICTED`.

---

# 28. Privacy and Data Minimization

## P9-SEC-070 — Raw Prompt Prohibition

WA SHALL NOT persist raw prompts or raw user messages.

---

## P9-SEC-071 — Artifact Byte Prohibition

WA SHALL NOT persist rendered Artifact bytes.

---

## P9-SEC-072 — Hidden Reasoning Prohibition

WA SHALL NOT persist hidden reasoning or model chain-of-thought.

---

## P9-SEC-073 — Credential Prohibition

WA SHALL NOT persist:

```text
authorization headers
service tokens
passwords
API keys
secret refs containing secret values
```

inside WorkEvidence or Job payloads.

---

## P9-SEC-074 — Compensation Prohibition

WA Foundation SHALL NOT persist individual compensation/payroll values.

---

## P9-SEC-075 — Human Activity Privacy

Individual Human WorkEvidence SHALL be treated at least as:

```text
CONFIDENTIAL
```

unless a more restrictive source policy applies.

---

# 29. Evidence Lifecycle

## P9-FR-070 — Immutable Active Evidence

An ACTIVE evidence source identity/hash SHALL not be mutated in place.

---

## P9-FR-071 — Supersession

Correction SHALL create a new WorkEvidence and link:

```text
supersedes_evidence_id
```

to the previous evidence.

---

## P9-FR-072 — Old Evidence Status

A superseded record SHALL transition to:

```text
SUPERSEDED
```

without deleting history.

---

## P9-FR-073 — Invalidation

Evidence known to be invalid MAY transition to:

```text
INVALIDATED
```

with bounded audit reason stored outside unrestricted content fields.

---

# 30. Read API Requirements

## P9-API-060 — Exact WorkEvidence

WA SHALL expose:

```text
GET /internal/v1/work-evidence/{work_evidence_id}
```

This endpoint SHALL require `work:evidence:detail:read`.

---

## P9-API-061 — Exact WorkAsset

WA SHALL expose:

```text
GET /internal/v1/work-assets/{work_asset_id}
```

---

## P9-API-062 — WorkAsset Evidence Lineage

WA SHALL expose:

```text
GET /internal/v1/work-assets/{work_asset_id}/evidence
```

This endpoint SHALL require `work:evidence:detail:read`.

ordered:

```text
PRIMARY first
then SUPPORTING by occurred_at / evidence_id
```

---

## P9-API-063 — Bounded WorkAsset Query

WA SHALL expose:

```text
GET /internal/v1/work-assets
```

with bounded filters.

At least one of:

```text
actor_ref
project_ref
```

SHALL be required.

---

## P9-API-064 — Query Time Range

A collection query SHALL require bounded:

```text
occurred_from
occurred_to
```

Maximum range:

```text
366 days
```

---

## P9-API-065 — Pagination

Default:

```text
limit = 50
```

Maximum:

```text
limit = 200
```

Pagination SHALL use an opaque cursor.

---

## P9-API-066 — Stable Ordering

Default ordering:

```text
occurred_at DESC
work_asset_id DESC
```

---

## P9-SEC-080 — Read Callers

Initial protected read callers MAY include:

```text
nex-ae-api
nex-ag
```

with the least privilege required for each route:

```text
work:evidence:read
work:evidence:detail:read   [only when individual evidence is required]
work:evidence:audit:read    [only for audit/replay/conflict provenance]
```

Direct browser access is not part of P9 Foundation.

---

# 31. Source Reconciliation / Backfill

## P9-REL-020 — Need for Reconciliation

Because source notifications are non-blocking, P9 SHALL provide bounded
reconciliation to recover missed notifications.

---

## P9-API-070 — AE AgentResult Reconciliation Source

AE SHALL provide a bounded source-ref listing:

```text
GET /internal/v1/wa-sources/agent-results
```

with:

```text
created_after
created_before
limit
cursor
```

returning refs/hashes only.

---

## P9-API-071 — AE Artifact Reconciliation Source

AE SHALL provide:

```text
GET /internal/v1/wa-sources/artifacts
```

with bounded time/cursor filters and refs/hashes only.

---

## P9-API-072 — WC Supporting Reconciliation Resolution

Initial Foundation SHALL NOT require an independent WC WorkResult reconciliation
listing endpoint.

When `AE_AGENT_RESULT` is discovered through normal intake or bounded AE
reconciliation, WA SHALL re-resolve the corresponding WC WorkResult by exact
AgentExecution/Claim lineage.

Thus a missed independent WC→WA notification does not exist as a separate
Foundation recovery problem.

---

## P9-REL-021 — Reconciliation Mode

WA SHALL support an operator-triggered or startup-bounded reconciliation mode.

No continuous general scheduler is required.

---

## P9-REL-022 — Reconciliation Idempotency

Reconciliation SHALL call the same source identity/idempotency path as normal
intake.

---

# 32. Service Token Configuration

## P9-SEC-090 — WA Outbound Tokens

WA runtime SHALL support:

```text
NEX_WA_TO_AE_SERVICE_TOKEN
NEX_WA_TO_WC_SERVICE_TOKEN
NEX_WA_TO_OA_SERVICE_TOKEN
NEX_WA_TO_EOS_SERVICE_TOKEN
```

and secret-ref equivalents in protected environments.

---

## P9-SEC-091 — AE Outbound WA Token

AE SHALL support:

```text
NEX_AE_TO_WA_SERVICE_TOKEN
```

for source notification.

---

## P9-SEC-092 — No Mandatory WC→WA Notification Token

Initial Foundation does not require a WC→WA source-notification token because
WC WorkResult is resolved by WA as supporting evidence through
`NEX_WA_TO_WC_SERVICE_TOKEN` (or its secret-ref equivalent).

A future independent WC→WA delivery path requires an explicit later contract.

---

## P9-SEC-093 — Signed-Only Protected Profile

Protected staging/release acceptance SHALL use signed service-token mode, not
test-mock authority.

---

# 33. Service Registry Integration

## P9-RUN-010 — Worker Heartbeat Registry

Shared heartbeat `SERVICE_IDS` SHALL include:

```text
nex-wa
```

---

## P9-RUN-011 — Service Log Registry

Shared service-log service vocabulary SHALL include `nex-wa` wherever a static
catalog is used.

---

## P9-RUN-012 — Runtime Endpoint Registry

Shared service endpoint registry SHALL include:

```text
nex-wa
NEX_WA_BASE_URL
http://127.0.0.1:8108
```

---

## P9-RUN-013 — PostgreSQL Target Registry

`POSTGRES_TEST_TARGETS` or current equivalent SHALL include WA.

---

## P9-RUN-014 — Deployment Catalog

Deployment artifact/process catalogs SHALL include WA API and consumer.

---

# 34. Observability

## P9-NFR-001 — Bounded Metrics

WA SHALL expose bounded operational signals for:

```text
queued Jobs
running Jobs
failed/dead-letter Jobs
oldest runnable age
ingest success/failure
source hash conflict
evidence reuse
stale Job recovery
consumer heartbeat
```

---

## P9-NFR-002 — No High-Cardinality Human Metric Labels

Metrics SHALL NOT use raw:

```text
subject_id
artifact_id
project_id
job_id
```

as unbounded metric labels.

---

## P9-NFR-003 — Structured Logs

WA logs SHALL include bounded:

```text
trace_id
request_id
job_id
source_type
status
error_code
```

where applicable.

Raw source content SHALL not be logged.

---

## P9-NFR-004 — Operational Events

WA SHOULD emit bounded events for:

```text
evidence admitted
source conflict
job dead-lettered
stale Job recovered
reconciliation completed
```

without sensitive payloads.

---

# 35. Readiness and Health

## P9-RUN-020 — Liveness

`nex-wa-api` SHALL expose:

```text
/health
```

or the Platform-standard liveness equivalent.

---

## P9-RUN-021 — Readiness

`nex-wa-api` SHALL expose:

```text
/ready
```

and require:

```text
WA DB reachable
required migrations current
```

---

## P9-RUN-022 — Consumer Readiness

Consumer package/runtime check SHALL verify:

```text
WA DB reachable
service_jobs exists
service_worker_heartbeats exists
wa_work_evidence exists
wa_work_asset exists
wa_work_asset_evidence exists
```

---

# 36. Error Taxonomy

## P9-ERR-001 — Invalid Intake

```text
WA_INTAKE_INVALID
HTTP 400
retryable=false
```

---

## P9-ERR-002 — Unsupported Source Type

```text
WA_SOURCE_TYPE_UNSUPPORTED
HTTP 422
retryable=false
```

---

## P9-ERR-003 — Caller Forbidden

```text
WA_CALLER_FORBIDDEN
HTTP 403
retryable=false
```

---

## P9-ERR-004 — Source Not Found

```text
WA_SOURCE_NOT_FOUND
HTTP 404
retryable=false
```

---

## P9-ERR-005 — Source Unavailable

```text
WA_SOURCE_UNAVAILABLE
HTTP 503
retryable=true
```

---

## P9-ERR-006 — Source Hash Mismatch

```text
WA_SOURCE_HASH_MISMATCH
HTTP 409
retryable=false
```

---

## P9-ERR-007 — Source Idempotency Conflict

```text
WA_SOURCE_IDEMPOTENCY_CONFLICT
HTTP 409
retryable=false
```

---

## P9-ERR-008 — Actor Unverified

```text
WA_ACTOR_UNVERIFIED
HTTP/worker semantic failure
retryable=false
```

Dependency outage is separately retryable.

---

## P9-ERR-009 — Project Unverified

```text
WA_PROJECT_UNVERIFIED
retryable=false
```

Dependency outage is separately retryable.

---

## P9-ERR-010 — Supporting Source Not Ready

```text
WA_SUPPORTING_SOURCE_NOT_READY
retryable=true
```

Used only when the authoritative Agent completion barrier proves that a WC
WorkResult should exist, but its bounded supporting projection is temporarily
not queryable.

A lineage mismatch or conflicting WorkResult is not this condition; it fails
closed as a non-retryable evidence/source conflict.

---

## P9-ERR-011 — Evidence Conflict

```text
WA_EVIDENCE_CONFLICT
retryable=false
```

---

## P9-ERR-012 — Store Unavailable

```text
WA_STORE_UNAVAILABLE
HTTP 503
retryable=true
```

---

## P9-ERR-013 — AgentResult Not Complete

```text
WA_AGENT_RESULT_NOT_COMPLETE
retryable=true
```

Used when the AgentResult exists but the authoritative AgentExecution /
required ResultDelivery completion barrier has not closed.

---

## P9-ERR-014 — Job Ownership Lost

```text
WA_JOB_OWNERSHIP_LOST
retryable=false for the stale settlement attempt
```

Used when a worker attempts to settle a Job after its claim fence has been
invalidated by recovery/requeue.

---

# 37. Retention

## P9-NFR-010 — No Automatic Physical Purge in Foundation

P9 Foundation SHALL NOT implement automatic physical WorkEvidence purge.

This avoids deleting audit lineage before governance policy is closed.

---

## P9-NFR-011 — Source Content Retention Independence

Source Artifact bytes may be archived/deleted under source policy without WA
copying those bytes.

WA MAY retain approved identity/hash/provenance.

---

## P9-NFR-012 — Future Retention Policy

A versioned WA retention policy is deferred.

Its absence SHALL NOT block P9 Foundation closure because P9 stores no raw
Artifact content.

---

# 38. Performance and Capacity

## P9-NFR-020 — Asynchronous Intake

Source notification API SHALL return after durable enqueue, not after full
source processing.

---

## P9-NFR-021 — Intake Latency Target

Under normal local/staging conditions, durable intake response SHOULD complete
within:

```text
p95 <= 500 ms
```

excluding upstream ingress/TLS network overhead.

This is an engineering target, not a business correctness condition.

---

## P9-NFR-022 — Consumer Throughput

Foundation SHALL prove at least:

```text
100 concurrently admitted intake requests
```

without duplicate WorkEvidence.

No fixed high-throughput production SLA is frozen in P9.

---

## P9-NFR-023 — Backpressure

Queue depth MAY grow under load without rejecting valid source authority.

Admission backpressure MAY return retryable 503 only when durable enqueue
cannot be guaranteed.

---

# 39. Contribution Candidate Boundary

## P9-CAND-001 — P9.2/P9.3 Exclusion

P9.2/P9.3 SHALL NOT implement a contribution formula.

---

## P9-CAND-002 — Artifact Count Is Not Human Effort

Human effort SHALL NOT be computed solely from:

```text
Artifact count
document count
message count
ownership count
```

---

## P9-CAND-003 — Candidate Persistence Timing

`wa_contribution_candidate` SHALL not be required before P9.5.

---

## P9-CAND-004 — Candidate Authority

Any later candidate remains:

```text
non-authoritative
```

until downstream confirmation.

---

# 40. Golden C Handoff Requirements

## P9-GC-001 — No Final MM

WA SHALL NOT produce authoritative:

```text
0.05 MM finalized allocation
```

in Foundation.

---

## P9-GC-002 — No Monetary Cost

WA SHALL NOT multiply contribution by compensation.

---

## P9-GC-003 — Future Candidate Envelope

P9.5 candidate, if implemented, SHALL provide at least:

```text
actor_ref
project_ref
period_start
period_end
evidence_set_hash
method_ref
method_version
candidate_value
candidate_unit
confidence
completeness
candidate_hash
```

---

## P9-GC-004 — Golden C Authority

Golden C/EOS remains authority for:

```text
confirmation/finalization
0.05-MM
compensation
LaborCostBasis
Project Labor Cost
Management Ledger
Project P/L
```

---

# 41. NSL / WC Delegation Explicit Exclusion

## P9-X-001 — No NSL Foundation Dependency

P9 Foundation SHALL NOT require:

```text
.ns
.nso
.nsp
NSL Controlled WRITE
Skill Pack
```

---

## P9-X-002 — No Evidence Registration Delegation

WA SHALL NOT create a WC WorkItem merely to register existing evidence.

---

## P9-X-003 — Future Analysis Exception

A later semantic analysis task MAY use WC Delegation only when genuinely new
work must be performed.

This is outside initial Foundation acceptance.

---

# 42. Source-Specific Admission Algorithms

## P9-ALG-001 — AgentResult Admission

Worker SHALL:

```text
1. fetch exact AE projection
2. match tenant/result/source hash
3. require AgentResult SUCCEEDED/PARTIAL
4. require AgentExecution SUCCEEDED
5. require correct required ResultDelivery ACKNOWLEDGED
6. validate agent type
7. validate CA/PA/EA project + claim lineage
8. verify Project in EOS when project_id exists
9. normalize AGENT actor
10. derive deterministic evidence ID
11. create/reuse AgentResult WorkEvidence
12. derive Agent WorkAsset from agent_execution_id
13. bind PRIMARY evidence
14. for CA/PA/EA resolve WC WorkResult by exact execution/claim lineage
15. create/reuse WC WorkResult WorkEvidence
16. bind SUPPORTING evidence to the same WorkAsset
```

If step 4/5 is not yet satisfied, return a retryable
`WA_AGENT_RESULT_NOT_COMPLETE` and create no positive WorkEvidence.

If WC is temporarily unavailable in step 14, retry the same AgentResult Job.
A lineage mismatch fails closed and does not create a second WorkAsset.

---

## P9-ALG-002 — Artifact Admission

Worker SHALL:

```text
1. fetch exact AE Artifact version projection
2. require READY
3. match tenant/version/content hash
4. resolve/verify Human owner against OA when Human-owned
5. normalize HUMAN actor
6. verify Project only when authoritative ProjectRef exists
7. derive deterministic evidence ID
8. create/reuse ownership/deliverable WorkEvidence
9. derive Human Artifact WorkAsset
10. bind PRIMARY evidence
```

Artifact ownership SHALL not create Human effort units.

---

## P9-ALG-003 — WC WorkResult Supporting Resolution

This algorithm is invoked from `P9-ALG-001`; it is not a mandatory independent
WA intake Job in the initial Foundation.

Worker SHALL:

```text
1. lookup exact WC WorkResult by AgentExecution/Claim lineage
2. match tenant/result hash
3. verify source_execution_ref
4. verify Agent/claim-generation/assignment lineage
5. create/reuse WorkResult WorkEvidence
6. bind to the already-created/reused Agent WorkAsset
```

WC dependency unavailability is retryable for the owning AgentResult Job.
Semantic lineage mismatch is non-retryable and fails closed.

---

# 43. Source Notification Algorithms

## P9-ALG-010 — AgentResult Notification Payload

AE SHALL send:

```text
source_type          = AE_AGENT_RESULT
source_ref           = agent_execution_id
source_revision_ref  = result_id
source_hash          = result_hash
```

---

## P9-ALG-011 — Artifact Notification Payload

AE SHALL send:

```text
source_type          = AE_ARTIFACT
source_ref           = artifact_id
source_revision_ref  = artifact_version_id
source_hash          = artifact_content_hash
```

---

## P9-ALG-012 — WorkResult Supporting Resolution Key

WC does not send a mandatory independent WA notification in the initial
Foundation.

WA resolves supporting WorkResult using the verified primary AgentResult
lineage:

```text
tenant_id
agent_execution_id
source_claim_ref
source_claim_generation
source_assignment_ref
agent_id
```

The returned WorkResult projection supplies its own exact `result_id`,
`revision_no`, and `result_hash` for supporting WorkEvidence identity.

---

# 44. Query Privacy Projection

## P9-SEC-100 — Default WorkAsset Projection

Default WorkAsset read SHALL expose:

```text
work_asset_id
asset_type
actor_type
actor_ref
agent_type_snapshot
project_ref
occurred_at
classification
asset_status
version
```

No source raw payload.

---

## P9-SEC-101 — Evidence Projection

Evidence lineage read SHALL expose refs/hashes but not source content.

---

## P9-SEC-102 — Restricted Filtering

A caller lacking the required detailed evidence scope SHALL receive a
redacted/denied response rather than downgraded private content.

---

# 45. Testing Requirements

## P9-TEST-001 — Unit Tests

Every new domain function SHALL have automated unit tests.

---

## P9-TEST-002 — Test Design

For deterministic methods, tests SHALL include as applicable:

```text
boundary value
robustness
worst-case / conflict
idempotency
negative authorization
cross-tenant
```

---

## P9-TEST-003 — Regression

Every source change SHALL run relevant unit + regression tests before commit
synchronization.

---

## P9-TEST-004 — PostgreSQL Required Tests

The following SHALL use actual PostgreSQL, not only mocks:

```text
unique source identity
concurrent SKIP LOCKED claim
multiple consumers
atomic evidence/asset transaction
stale RUNNING recovery
retry/dead-letter/replay
cross-tenant constraints
```

---

## P9-TEST-005 — Coverage Gate

Platform quality SHALL remain at least:

```text
Statement >= 96%
Branch    >= 94%
```

---

## P9-TEST-006 — No Playwright Requirement

P9 Foundation has no mandatory browser UI.

Playwright is therefore not required for P9 Foundation closure.

If a WA browser surface is introduced later, it requires a separate acceptance
addition.

---

# 46. Contract Tests

## P9-TEST-010 — Positive Contract Fixtures

At minimum:

```text
valid completed AgentResult source projection
valid Artifact source projection
valid WC supporting-by-execution projection
valid intake
idempotent intake reuse
valid Human subject verification
valid Project verification
valid historical membership verification
valid WorkEvidence
valid WorkAsset
valid binding
valid paginated query
```

---

## P9-TEST-011 — Negative Contract Fixtures

At minimum:

```text
unsupported source type
source hash mismatch
same identity/different hash
cross-tenant source
unknown Human subject
inactive Human subject
CA/PA/EA missing Project
IA Project spoof
Artifact not READY
Artifact version mismatch
WC execution mismatch
pre-ACK AgentResult positive-admission attempt
duplicate logical Agent work
stale worker settlement after recovery
raw content in Job payload
caller without work:evidence:ingest
basic read caller requesting detailed evidence
source read caller other than nex-wa
```

---

# 47. Reliability Acceptance

## P9-TEST-020 — Duplicate Intake

10 identical intake requests SHALL produce:

```text
1 semantic Job
1 semantic WorkEvidence
1 semantic WorkAsset
```

---

## P9-TEST-021 — Concurrent Intake

At least 100 concurrently submitted source notifications SHALL complete
without duplicate semantic evidence.

---

## P9-TEST-022 — Concurrent Consumer

At least 2 consumer processes/instances SHALL prove:

```text
SKIP LOCKED claim isolation
no duplicate semantic evidence
```

---

## P9-TEST-023 — Crash After Evidence Commit

Test SHALL simulate:

```text
WA transaction commit
→ process failure before Job complete
→ stale recovery/retry
```

and prove no duplicate evidence.

---

## P9-TEST-024 — Dead-Letter

Retry exhaustion SHALL create terminal dead-letter evidence with no silent
loss.

---

## P9-TEST-025 — Replay

Operator replay SHALL create a new Job with explicit lineage while reusing
existing semantic WorkEvidence when source semantics are unchanged.

---

## P9-TEST-026 — Stale Worker Settlement Fencing

Test SHALL prove:

```text
Worker A claims Job
→ A becomes stale
→ fenced recovery requeues Job
→ Worker B claims recovered Job
→ Worker A wakes and attempts settlement
→ A receives WA_JOB_OWNERSHIP_LOST with zero mutation
→ B completes successfully
```

No duplicate WorkEvidence/WorkAsset is permitted.

---

# 48. Security Acceptance

## P9-TEST-030 — Wrong Audience

Token with non-`nex-wa` audience SHALL be rejected at WA intake/read.

---

## P9-TEST-031 — Wrong Caller

Service not in allowed producer list SHALL receive 403.

---

## P9-TEST-032 — Raw Payload Rejection

Intake/Job payload containing prohibited keys/content SHALL fail before
durable processing.

---

## P9-TEST-033 — Cross-Tenant Source

Source projection tenant mismatch SHALL fail closed.

---

## P9-TEST-034 — Human Identity Failure

Inactive/unknown Human owner SHALL not become WorkEvidence.

---

## P9-TEST-035 — Detailed Evidence Scope

Caller with only `work:evidence:read` SHALL NOT receive individual
WorkEvidence/source lineage requiring `work:evidence:detail:read`.

---

## P9-TEST-036 — Audit Scope

Supersession/conflict/replay provenance SHALL require
`work:evidence:audit:read`; a basic read caller receives redacted/denied output.

---

# 49. Source Equivalence Acceptance

## P9-TEST-040 — AgentResult + WorkResult

One PA/CA/EA execution producing AgentResult then WC WorkResult SHALL result in:

```text
1 Agent WorkAsset
2 evidence facts
  PRIMARY AgentResult
  SUPPORTING WorkResult
```

not two WorkAssets.

---

## P9-TEST-041 — AgentResult + Artifact

An AgentResult referencing an Artifact SHALL not automatically turn the Human
Artifact owner into Human effort authority.

---

## P9-TEST-042 — IA Project Neutrality

IA result mentioning a Project in text but lacking authoritative ProjectRef
SHALL remain:

```text
project_ref = null
```

---

## P9-TEST-043 — AgentResult Completion Barrier

The same authoritative AgentResult SHALL be tested in two states:

```text
A. required ResultDelivery = PENDING
   → no positive WA WorkEvidence

B. required ResultDelivery = ACKNOWLEDGED
   + AgentExecution = SUCCEEDED
   → PRIMARY Agent WorkEvidence admitted
```

For CA/PA/EA, the admitted path SHALL also resolve and bind the matching WC
WorkResult as SUPPORTING evidence.

---

# 50. Human Evidence Acceptance

## P9-TEST-050 — Human-Owned READY Artifact

A valid READY Artifact with verified Human owner SHALL create:

```text
HUMAN_OWNED_ARTIFACT
```

WorkAsset and:

```text
OWNERSHIP_OR_DELIVERABLE_EVIDENCE
```

PRIMARY evidence.

---

## P9-TEST-051 — Human Effort Not Inferred

The same Artifact SHALL NOT automatically create:

```text
HumanEffortCandidate
MM
hours
performance score
```

---

# 51. Project Attribution Acceptance

## P9-TEST-060 — Background Agent Project

CA/PA/EA AgentResult with authoritative Project/claim lineage SHALL preserve
that ProjectRef.

---

## P9-TEST-061 — Missing Background Project

CA/PA/EA without required Project lineage SHALL fail closed.

---

## P9-TEST-062 — Human Project Membership

Where a Human Artifact is explicitly Project-scoped, historical membership at
`occurred_at` SHALL be verified when policy requires membership.

---

# 52. Reconciliation Acceptance

## P9-TEST-070 — Missed AE Notification

If AgentResult notification is skipped, bounded reconciliation SHALL enqueue
and admit it exactly once.

---

## P9-TEST-071 — Missed Artifact Notification

Same requirement for READY Artifact.

---

## P9-TEST-072 — WC Supporting Re-resolution

When an AgentResult is recovered through bounded AE reconciliation, WA SHALL
re-resolve the matching WC WorkResult by exact execution/claim lineage and bind
it once as SUPPORTING evidence.

No independent missed WC→WA notification path is required.

---

# 53. Performance Acceptance

## P9-TEST-080 — Intake p95

Protected environment SHOULD demonstrate:

```text
p95 <= 500ms
```

for durable enqueue under nominal load.

---

## P9-TEST-081 — No API Inline Source Processing

The intake route test SHALL prove that full source resolution is executed by
consumer, not by API request path.

---

# 54. Protected P9 Foundation E2E

## P9-E2E-001 — Canonical Journey

Protected P9 final journey SHALL prove:

```text
1. Frozen WA reconciliation gate is PASS before P9.2 domain coding evidence is accepted.
2. nex-wa-api / consumer start with current migrations.
3. Human-owned READY Artifact exists.
4. CA/PA/EA AgentResult exists with Project/claim lineage while required delivery is PENDING.
5. WA does NOT admit that pre-ACK AgentResult as positive post-work evidence.
6. Required WC_WORK_RESULT delivery becomes ACKNOWLEDGED and AgentExecution becomes SUCCEEDED.
7. AE sends concurrent AgentResult/Artifact source notifications.
8. WA accepts only refs/hashes and enqueues.
9. Consumers claim through PostgreSQL SKIP LOCKED.
10. Source owner projections are re-read.
11. OA/EOS authority is verified as required.
12. Human Artifact becomes ownership/deliverable evidence.
13. Completed AgentResult becomes Agent execution PRIMARY evidence.
14. WA resolves WC WorkResult by exact AgentExecution/Claim lineage.
15. WC WorkResult becomes SUPPORTING evidence.
16. One Agent work produces only one Agent WorkAsset.
17. No creator/manager approval occurs.
18. No WC Delegation is created for evidence.
19. No NSL is executed.
20. Source hash conflict fails closed.
21. Cross-tenant source fails closed.
22. Worker crash after local commit is recovered.
23. A stale pre-recovery worker cannot settle the recovered Job.
24. No duplicate WorkEvidence is created.
25. Basic read scope cannot access detailed Human evidence lineage.
26. Detailed/audit scopes expose only their bounded authorized projections.
27. No salary, MM, labor cost or P/L is created.
28. Full regression/coverage gate passes.
29. Runtime residue is zero.
```

---

# 55. P9 Phase Mapping

Recommended implementation mapping:

```text
P9.0
Pre-Architecture / Source Audit / Contract Closure / SRS

P9.2
[only after P9-GATE-001 PASS]
nex-wa service + DB + JobQueue + WorkEvidence/WorkAsset

P9.3
AE/WC source projection + notification + intake + source equivalence

P9.4
OA/EOS authority + HUMAN/AGENT + Project attribution + privacy

P9.5
Contribution Candidate, only after foundation is stable

P9.6
query / reconciliation / backfill / reliability / retention policy boundary

P9.7
Protected E2E / Full Gate / Final As-Built
```

P9.1 Source Audit/Contract Closure is already completed before this SRS.

---

# 56. Traceability to Contract Closure

| Contract Closure | SRS Coverage |
|---|---|
| CC-01~04 service/DB/queue | §§5–9 |
| CC-05~08 job/recovery | §§8–10 |
| CC-09~12 no approval/NSL/delegation | §§26, 41 |
| CC-13~15 source set | §§13–20 |
| CC-16~20 actor/project | §§15–20 |
| CC-21~25 WorkAsset/Evidence/equivalence | §§21–25 |
| CC-26~27 deferred WorkFact/candidate | §§39 |
| CC-28 source independence | §§13, 30 |
| CC-29 no broker | §8 |
| CC-30 Golden C authority | §40 |
| CC-31 AgentResult completion barrier | §§13–15, 42, 49, 54 |
| CC-32 stale-job fencing/CAS | §§9–10, 47, 54 |
| CC-33 WC supporting resolution | §§13, 19, 25, 42–43, 49, 52, 54 |
| CC-34 Frozen-WA reconciliation gate | §2 / P9-GATE-001, §§55–58 |
| CC-35 P9-CA01 reconciliation PASS | §2 / P9-GATE-001, §§55–58 |
| CC-36 asset-relative binding role | §§21–25 / P9-DB-018, P9-FR-066 |
| CC-37 PRIMARY/hash/version ownership | §§23–26 / P9-FR-053~054, P9-DB-042 |
| Future Agent execution-authority compatibility | §15 / P9-FR-026, §59 |

---

# 57. Implementation Constraints

The implementation SHALL follow these engineering rules:

```text
refactor before feature addition when structure requires it
one bounded feature at a time
unit tests with every feature
PostgreSQL regression after persistence changes
no code duplication of shared JobQueue/WorkerRunner
no direct DB shortcuts
no hidden manual recovery steps in acceptance
commit synchronization only after regression passes
```

---

# 58. P9 SRS Exit Criteria

The SRS is implementation-ready when the team accepts:

```text
service topology
port/environment
DB names
JobQueue model
stale recovery + fenced settlement
source routes
service scopes
AgentResult completion barrier
WC supporting-resolution contract
WorkEvidence schema
WorkAsset schema
binding schema
binding-role ownership
WorkAsset hash/version projection
source equivalence
Human/Agent normalization
Project validation
privacy/read/detail/audit scopes
read APIs
reconciliation
Frozen-WA P9.2 coding gate
test/acceptance gates
Golden C boundary
```

---

# 59. Final Requirement Position

P9 NeX-WA Foundation SHALL implement the following minimal authoritative
behavior:

```text
Authoritative source fact
        ↓
authoritative completion/admissibility boundary
        ↓
best-effort post-completion notification
        ↓
durable WA Job
        ↓
background re-verification
        ↓
immutable/idempotent WorkEvidence
        ↓
bounded WorkAsset
        ↓
privacy-safe query
```

while preserving:

```text
Evidence Admission != Business Approval

HUMAN/AGENT identity stays external
Project authority stays EOS
source work state stays source-owned
WA failure does not invalidate source work
AgentResult positive admission requires authoritative completion/delivery ACK
WC WorkResult is resolved as supporting lineage, not independent mandatory ingress
stale RUNNING recovery invalidates old worker settlement authority
AgentResult/WorkResult/Artifact are not double-counted
Artifact ownership is not Human effort
detailed Human evidence requires explicit privacy scope
LLM is not evidence authority
NSL is not required
WC Delegation is not required
Golden C remains financial authority
future Agent WorkAsset semantics do not intrinsically require WC lineage
unknown autonomous Agent execution-authority profiles fail closed until Controlled Amendment
```

The intended P9 completion state is:

> **NeX Platform can automatically and safely preserve evidence-backed Human-owned
> deliverables and Agent-executed work as a durable Work Asset history, under
> concurrent load and restart/replay conditions, without creating a new
> workflow, approval, scheduling, or accounting subsystem.**
