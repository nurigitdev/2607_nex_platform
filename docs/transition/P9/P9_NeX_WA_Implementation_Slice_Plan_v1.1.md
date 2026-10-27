# P9 — NeX-WA (Work Asset)
# Implementation Slice Plan v1.1

**Status:** PRE-IMPLEMENTATION BASELINE / P9-CA01 PASS / P9-S01 AUTHORIZED
**Phase:** P9 — NeX-WA / Work Asset Foundation
**Platform:** NeX Platform v2.1
**Pre-Architecture:** `P9_NeX_WA_Pre_Architecture_Decision_v1.2.md`
**Source Audit:** `P9_NeX_WA_Source_Audit_and_Gap_Analysis_v1.0.md`
**Contract Closure:** `P9_NeX_WA_Contract_Closure_v1.1.md`
**SRS:** `P9_NeX_WA_SRS_v1.1.md`
**P8 Predecessor:** `P8_Final_AsBuilt_Baseline_and_P9_Handoff_v1.2.md` + merged P8-DEMO baseline
**Entry Branch:** `transition/p4-agent-runtime-foundation`
**Entry HEAD:** `c3a1ea907387b67fe7a63407e4d668d13b1be8e7`
**Quality Floor:** Statement ≥ 96%, Branch ≥ 94% for P9-owned/changed code and current repository Full Gate
**Date:** 2026-10-27

---

# 1. Purpose

This document converts the closed P9 NeX-WA architecture and SRS into bounded
implementation, regression, protected-evidence and commit units.

The plan intentionally keeps P9 small.

Canonical P9 Foundation:

```text
Authoritative completed source
        ↓
best-effort exact-ref notification
        ↓
nex-wa-api
        ↓
WA_EVIDENCE_INGEST
        ↓
WA-owned service_jobs
        ↓
nex-wa-evidence-consumer
        ↓
deterministic source verification
        ↓
immutable / idempotent WorkEvidence
        ↓
bounded WorkAsset
        ↓
privacy-safe read / reconciliation
```

P9 is not another workflow engine.

P9 does not implement:

```text
Scheduler
Agent orchestration replacement
new approval engine
new delegation model
NSL dependency
external broker
payroll
financial labor cost
Project P/L
performance scoring
```

---

# 2. Current Implementation Entry Rule

P9 documentation is sufficiently closed for:

```text
SRS
Implementation Slice Plan
source inspection
test design
migration planning
contract planning
```

P9-CA01 has now closed the production-domain coding gate.

```text
P9-CA01 Frozen WA Reconciliation = PASS
unresolved material conflict = 0
P9.2 domain coding = AUTHORIZED
```

This is inherited directly from Contract Closure v1.1 and SRS v1.1.

---

# 3. P9-CA01 — Frozen WA Reconciliation and Coding Entry Gate

Before P9-S01 production domain code is committed, materialize and reconcile:

```text
23_NeX_Work_Asset_Human_Effort_and_Labor_Allocation_Design_v2.0.docx

23_NeX_Work_Asset_Human_Effort_and_Labor_Allocation_
Implementation_Contracts_v2.0.zip
```

against:

```text
P8 Final As-Built v1.2
merged P8-DEMO baseline
P9 PAD v1.2
P9 Source Audit v1.0
P9 Contract Closure v1.1
P9 SRS v1.1
```

Each material finding SHALL be classified:

```text
COMPATIBLE
ADDITIVE / INCORPORATE
CONFLICT / CONTROLLED AMENDMENT REQUIRED
NOT APPLICABLE TO P9 FOUNDATION
```

P9-CA01 exit:

```text
Frozen/reference materialized
semantic comparison complete
no unresolved ownership/SoR conflict
no unresolved identity conflict
no unresolved approval/result-publication conflict
no unresolved WorkEvidence/WorkAsset conflict
coding entry = PASS
```

If a material conflict exists:

```text
STOP
→ P9 Controlled Amendment
→ affected SRS / contract revalidation
→ resume only after closure
```

Recorded result:

```text
P9_CA01_Frozen_WA_Reconciliation_and_Coding_Entry_Gate_v1.0.md
coding entry = PASS
next Slice = P9-S01
```

---

# 4. Implementation Strategy

P9 is implemented in four mandatory execution bands plus one optional band.

```text
P9.2  Core Foundation
      service / DB / queue / evidence / asset / worker

P9.3  Source Integration
      AE AgentResult / AE Artifact / WC supporting projection

P9.4  Authority / Project / Privacy
      OA / EOS / Human-Agent normalization / privacy

P9.6  Operational Maturity
      reconciliation / replay / observability / deployment / load

P9.7  Protected Acceptance / Final Freeze
      E2E / Full Gate / zero residue / Final As-Built
```

Optional:

```text
P9.5  Contribution Candidate
```

P9.5 is **not required** to close NeX-WA Foundation.

The default P9 Foundation plan is:

```text
P9.2 → P9.3 → P9.4 → P9.6 → P9.7
```

P9.5 may be activated only after P9.3/P9.4 have closed lineage, attribution and
privacy.

---

# 5. Quality and Commit Discipline

Every production Slice SHALL follow:

```text
1. inspect current source structure
2. refactor first if necessary
3. implement one bounded behavior
4. add/update automated tests
5. run focused regression
6. run owning-service Slice Gate
7. run protected evidence when claimed
8. git diff --check
9. commit only after PASS
10. synchronize before next Slice
```

Refactoring rule:

```text
small enabling refactor
→ same Slice allowed

large / cross-cutting refactor
→ separate Slice before feature
```

No Slice may hide structural debt behind feature code.

---

# 6. Gate Model

Repository development process uses:

```text
Slice Gate
Checkpoint Gate
Full Gate
```

P9 adopts the existing gate tools, but P9 uses the stronger P8/P9 quality floor.

P9 coverage requirement:

```text
Statement >= 96%
Branch    >= 94%
```

This P9-specific requirement overrides weaker generic historical minimums.

Gate cadence:

| Gate | P9 cadence |
|---|---|
| Slice Gate | every production Slice |
| Checkpoint Gate | S05, S15, S25 or earlier on risk escalation |
| Full Gate | S10, S20, S30 and final closure |
| Protected PostgreSQL | every persistence/recovery closure |
| Signed-service-token acceptance | source/authority and final protected closure |
| Playwright | not required unless a WA browser UI is introduced |
| Live generation | not required for WA Foundation |

Risk escalation to earlier Checkpoint/Full Gate is required when a Slice changes:

```text
shared runtime primitives
service auth / trust
cross-service contract
migration infrastructure
deployment/bootstrap
multiple owner services
quality infrastructure
```

---

# 7. P9 Baseline Invariants

All Slices inherit:

```text
P9-INV-01  WA is post-work evidence, not Work SoR.
P9-INV-02  WA is not Scheduler.
P9-INV-03  WA does not directly read another service DB.
P9-INV-04  Human identity remains OA-owned.
P9-INV-05  Agent identity/execution remains AE-owned.
P9-INV-06  WorkItem/Claim/Delegation remains WC-owned.
P9-INV-07  Project/ProjectMember remains EOS-owned.
P9-INV-08  Evidence Admission != Business Approval.
P9-INV-09  WA failure does not invalidate completed source work.
P9-INV-10  WorkEvidence is immutable or explicitly superseded.
P9-INV-11  Queue idempotency != Evidence idempotency.
P9-INV-12  AgentResult / WorkResult / Artifact are not independent contribution units.
P9-INV-13  Artifact ownership != Human effort.
P9-INV-14  Model output is not evidence authority.
P9-INV-15  NSL is not required for Foundation.
P9-INV-16  WC Delegation is not required for evidence registration.
P9-INV-17  Golden C owns final MM / cost / accounting / P/L.
P9-INV-18  Agent positive evidence requires authoritative completion barrier.
P9-INV-19  stale RUNNING recovery invalidates old worker settlement authority.
P9-INV-20  WC WorkResult is supporting lineage, not mandatory independent ingress.
```

Forward compatibility invariant:

```text
P9-INV-21

WA SHALL NOT require WC lineage as the intrinsic definition
of every future Agent WorkAsset.

WA requires an AE-proven execution-authority profile
and completion-evidence profile.

P9 v1 admits:
  IA          -> PROMPT / WORKSPACE_RESULT ACK
  CA/PA/EA    -> CLAIMED_WORKITEM / WC_WORK_RESULT ACK

Future autonomous profiles require Controlled Amendment.
Unknown profiles fail closed.
```

This keeps future PA Scheduler/Harness evolution possible without widening P9
Foundation now.

---

# 8. Target Runtime Shape

```text
                        ┌───────────────────────┐
                        │      nex-wa-api       │
                        │        :8108          │
                        └───────────┬───────────┘
                                    │
                             durable enqueue
                                    │
                                    ▼
                        ┌───────────────────────┐
                        │    WA service_jobs    │
                        │ WA_EVIDENCE_INGEST    │
                        └───────────┬───────────┘
                                    │
                         SKIP LOCKED claim
                                    │
                                    ▼
                  ┌────────────────────────────────┐
                  │ nex-wa-evidence-consumer      │
                  │ source adapter / verification  │
                  └────────────────┬───────────────┘
                                   │
                 ┌─────────────────┼───────────────────┐
                 │                 │                   │
                 ▼                 ▼                   ▼
           AE AgentResult      AE Artifact        WC WorkResult
             PRIMARY            PRIMARY            SUPPORTING
                 │                 │                   │
                 └─────────────────┴───────────────────┘
                                   │
                                   ▼
                     ┌─────────────────────────┐
                     │   NeX-WA PostgreSQL     │
                     │ WorkEvidence            │
                     │ WorkAsset               │
                     │ Asset↔Evidence          │
                     └─────────────────────────┘
```

Initial databases:

```text
nex_wa_dev
nex_wa_test
role = nex_wa_user
```

---

# 9. Migration Strategy

Do not invent cross-service migration numbering.

P9-S01 SHALL inspect the current repository migration conventions and freeze the
exact `database/nex-wa/migrations/` sequence before P9-S02.

Logical migration units:

```text
WA-M01  schema migration baseline
WA-M02  service_jobs foundation
WA-M03  service_worker_heartbeats
WA-M04  wa_work_evidence
WA-M05  wa_work_asset
WA-M06  wa_work_asset_evidence
```

Rules:

```text
service-local only
no cross-database FK
P8 migration prefixes remain immutable
actual filenames/IDs follow repository convention
```

---

# 10. Contract Deliverables

Foundation contracts SHALL include at least:

```text
wa_evidence_intake_request.v1
wa_evidence_intake_admission.v1

wa_agent_result_source_projection.v1
wa_artifact_source_projection.v1
wa_wc_work_result_source_projection.v1

wa_work_evidence.v1
wa_work_asset.v1
wa_work_asset_evidence_binding.v1

wa_work_evidence_collection.v1
wa_work_asset_collection.v1

wa_error.v1
```

P9.5 candidate contracts are not part of P9.2/P9.3 closure.

---

# 11. Mandatory Slice Sequence

## P9.2 — Core Foundation

### P9-S01 — NeX-WA Service Identity / Repository Skeleton

Goal:

```text
establish nex-wa as a first-class Platform owner
without adding domain behavior
```

Implement:

```text
services/nex-wa/nex_wa/
  __init__.py
  main.py
  app.py

service_id = nex-wa
port = 8108
NEX_WA_BASE_URL
WA dev/test database target registration
```

Extend exact shared registries discovered from current source:

```text
service identity
runtime endpoint
worker heartbeat vocabulary
service log vocabulary
PostgreSQL target catalog
deployment artifact catalog
runtime/process topology
service-token audience catalog
```

Add:

```text
artifact_id = nex-wa-runtime
process = nex-wa-api
process = nex-wa-evidence-consumer
```

Do not implement WorkEvidence yet.

Tests:

```text
service identity uniqueness
port/endpoint contract
registry completeness
no existing service regression
container/deployment catalog schema
```

Exit:

```text
nex-wa imports cleanly
service catalog accepts nex-wa
no domain table
Slice Gate PASS
```

---

### P9-S02 — WA PostgreSQL Bootstrap / Common Runtime Persistence

Goal:

```text
create owner-local WA persistence foundation
```

Implement:

```text
database/nex-wa/migrations/
schema_migrations
service_jobs
service_worker_heartbeats
```

Reuse existing canonical migration bodies/patterns.

Configure:

```text
NEX_WA_DATABASE_URL
NEX_WA_TEST_DATABASE_URL
nex_wa_dev
nex_wa_test
nex_wa_user
```

Tests:

```text
fresh DB migration
repeat migration
migration current
wrong DB identity rejection in protected test
service_jobs contract parity
heartbeat persistence
zero residue
```

Protected:

```text
actual nex_wa_test PostgreSQL required
```

Exit:

```text
WA DB current
queue/heartbeat tables current
no WA domain tables yet
Slice Gate PASS
```

---

### P9-S03 — WorkEvidence Persistence / Identity / Hash

Goal:

```text
implement immutable atomic evidence identity
```

Implement:

```text
wa_work_evidence
```

Fields per SRS:

```text
tenant_id
work_evidence_id
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
observed_at
classification
evidence_status
evidence_hash
supersedes_evidence_id
created_at
```

Implement deterministic:

```text
work_evidence_id = UUIDv5(source identity)
evidence_hash = canonical semantic hash
```

Constraints:

```text
unique exact source revision
HUMAN | AGENT
ACTIVE | SUPERSEDED | INVALIDATED
IA | CA | PA | EA when non-null
no cross-tenant supersession
no self-supersession
no global evidence_role; relationship role belongs to binding
```

Tests:

```text
same identity/same hash reuse
same identity/different hash conflict
cross-tenant negative
hash stability
source revision boundary
supersession constraints
```

Exit:

```text
WorkEvidence repository stable
actual PostgreSQL acceptance PASS
Slice Gate PASS
```

---

### P9-S04 — WorkAsset / Asset↔Evidence Persistence

Goal:

```text
introduce one logical work unit distinct from evidence multiplicity
```

Implement:

```text
wa_work_asset
wa_work_asset_evidence
```

Initial asset types:

```text
AGENT_EXECUTION_RESULT
HUMAN_OWNED_ARTIFACT
```

Asset states:

```text
ACTIVE
SUPERSEDED
INVALIDATED
```

Binding:

```text
PRIMARY
SUPPORTING
```

`binding_role` is the sole PRIMARY/SUPPORTING source of truth.
`wa_work_asset` does not duplicate `primary_evidence_id`.

Enforce:

```text
one ACTIVE WorkAsset has exactly one PRIMARY binding
one evidence cannot duplicate same asset binding
tenant alignment
asset hash binds stable fields plus sorted evidence bindings
exact replay preserves asset hash and version
```

Deterministic IDs:

```text
Agent asset:
  tenant_id + agent_execution_id

Human Artifact asset:
  tenant_id + artifact_id + artifact_version_id
```

Tests:

```text
one-primary invariant
binding uniqueness
tenant mismatch
deterministic asset IDs
version increment
supporting evidence fan-in
same evidence with asset-relative binding roles under exact lineage
no zero-primary ACTIVE asset
```

Exit:

```text
Evidence and Asset remain distinct
actual PostgreSQL PASS
Slice Gate PASS
```

---

### P9-S05 — WA Local Unit of Work / Semantic Idempotency

Goal:

```text
make evidence + asset + binding one restart-safe local semantic unit
```

Implement source-independent domain service:

```text
admit_normalized_evidence()
```

One local transaction:

```text
create/reuse WorkEvidence
create/update WorkAsset
create/reuse binding
commit
```

Job settlement remains outside this transaction and happens after commit.

Implement:

```text
same source semantics → reuse
source identity/hash conflict → typed failure
crash-after-commit replay → reuse
```

No source HTTP adapter yet.

Tests:

```text
atomic rollback
exact replay
crash after local commit
race on same evidence
race on same asset
one-primary enforcement
```

Protected PostgreSQL required.

### P9 Checkpoint Gate #1

After S05:

```text
P9 owner DB
WorkEvidence
WorkAsset
binding
local transaction
idempotency
```

must pass Checkpoint Gate.

---

### P9-S06 — Intake Contracts / Deterministic Job Identity

Goal:

```text
define the source-inspection request without trusting the payload
```

Implement schemas:

```text
wa_evidence_intake_request.v1
wa_evidence_intake_admission.v1
wa_error.v1
```

Initial external intake types:

```text
AE_AGENT_RESULT
AE_ARTIFACT
```

`WC_WORK_RESULT` is a valid internal supporting source type but not an initial
independent ingress.

Implement:

```text
job_id UUIDv5
idempotency_key sha256(canonical source identity)
```

Identity excludes `source_hash`.

Payload:

```text
tenant_id
source_type
source_ref
source_revision_ref
source_hash
trace/request/correlation refs
```

Reject raw:

```text
prompt
document body
artifact bytes
credentials
tokens
salary/payroll
unbounded payload
```

Tests:

```text
deterministic job identity
same identity/same payload reuse
same identity/different hash conflict
payload privacy rejection
unsupported source
contract positive/negative fixtures
```

Exit:

```text
contract validation PASS
Slice Gate PASS
```

---

### P9-S07 — nex-wa-api / Durable Enqueue / Service Authorization

Goal:

```text
accept exact source references and return after durable enqueue
```

Implement:

```text
POST /internal/v1/evidence-intake
```

Security:

```text
audience = nex-wa
DEFAULT_SERVICE_SCOPE
work:evidence:ingest
initial producer = nex-ae-api
```

Response:

```text
202 Accepted
job_id
status
source identity
idempotent_reuse
request_id
trace_id
```

API SHALL NOT:

```text
fetch source
normalize evidence
call OA/EOS
create WorkEvidence inline
```

Tests:

```text
wrong audience
wrong caller
missing scope
duplicate enqueue
hash conflict
DB unavailable
bounded p95 unit/integration baseline
```

Exit:

```text
durable enqueue proven
API remains thin
Slice Gate PASS
```

---

### P9-S08 — Evidence Consumer / Source Adapter Port

Goal:

```text
activate the WA background process without source-specific behavior
```

Implement:

```text
nex-wa-evidence-consumer
WaEvidenceSourceAdapter protocol
adapter registry
source-normalized envelope
```

Compose shared:

```text
SqlAlchemyJobQueue
WorkerRunnerConfig
WorkerHeartbeatEmitter
ServiceLogEmitter
```

Worker type:

```text
wa.evidence_consumer
```

Startup checks:

```text
DB reachable
migrations current
service_jobs exists
heartbeat table exists
WA domain tables current
adapter registry valid
```

No AE/WC source call yet; use controlled test adapter.

Tests:

```text
claim/complete
retry
graceful stop
heartbeat
unknown adapter fail-closed
raw payload rejection
```

Exit:

```text
consumer lifecycle proven
Slice Gate PASS
```

---

### P9-S09 — Fenced Stale-RUNNING Recovery

Goal:

```text
close the common JobQueue crash gap without creating AE RuntimeJob semantics
```

Implement P9-specific recovery composition.

Default:

```text
NEX_WA_STALE_JOB_SECONDS = 300
allowed = 60..3600
```

Eligible:

```text
status = RUNNING
locked_at older than cutoff
owner worker heartbeat absent/stale
```

Recovery CAS/fence SHALL compare:

```text
job_id
status RUNNING
locked_by
locked_at
```

or equivalent persisted claim token.

After recovery:

```text
old worker settlement authority = invalid
```

Implement typed:

```text
WA_JOB_OWNERSHIP_LOST
```

Tests:

```text
false stale negative
stale requeue
attempt exhaustion dead-letter
two recovery racers
old worker complete rejected
old worker fail rejected
old worker retry rejected
new worker completes
```

Protected actual PostgreSQL required.

Exit:

```text
recovery is fenced
no duplicate evidence
Slice Gate PASS
```

---

### P9-S10 — Core Read APIs / Readiness / P9.2 Core Closure

Goal:

```text
make the local WA domain independently operable
```

Implement:

```text
GET exact WorkEvidence
GET exact WorkAsset
GET WorkAsset evidence lineage
/health
/ready
consumer --check / equivalent readiness
```

Basic read authorization scaffolding:

```text
work:evidence:read
```

Detailed privacy scopes activate later in S20.

Run protected Core Foundation acceptance:

```text
fresh nex_wa_test
migrations current
100 duplicate intake requests
at least 2 consumers
SKIP LOCKED claim
crash-after-commit
stale recovery fencing
zero duplicate Evidence/Asset
zero residue
```

### P9-CA02 — Core Foundation Closure

Required:

```text
S01-S10 complete
Checkpoint #1 PASS
actual PostgreSQL PASS
contract validation PASS
P9 Full Gate PASS
Statement >= 96%
Branch >= 94%
zero residue
```

No source integration is claimed yet.

---

# 12. P9.3 / P9.4 — Source and Authority Integration

### P9-S11 — AE AgentResult Safe WA Projection

Goal:

```text
provide exact post-work AgentResult evidence without raw result content
```

Add AE internal route:

```text
GET /internal/v1/wa-sources/agent-results/{result_id}
```

Caller:

```text
nex-wa
DEFAULT_SERVICE_SCOPE
work:source:read
```

Projection includes:

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
WorkItem / Claim / generation / Assignment lineage
created_at

agent_execution_state
required_delivery_target_type
required_delivery_state
required_delivery_ref
delivery_acknowledged_at
```

No raw result text.

Tests:

```text
IA project-neutral
CA/PA/EA required lineage
pre-ACK projection
post-ACK projection
wrong caller
cross-tenant
privacy scan
```

Exit:

```text
AgentResult projection is completion-aware
AE Slice Gate PASS
```

---

### P9-S12 — AE Artifact Safe WA Projection

Goal:

```text
provide exact versioned Artifact evidence without bytes
```

Add:

```text
GET /internal/v1/wa-sources/artifacts/{artifact_id}/versions/{artifact_version_id}
```

Projection:

```text
tenant
artifact_id
artifact_version_id
status
owner_actor_ref
workspace_ref
source_content_hash
artifact_content_hash
created_at
classification
producer_execution_ref
```

Admission source condition:

```text
READY only
```

Tests:

```text
exact version
version mismatch
not READY
content hash mismatch
Human owner
Agent-produced/Human-owned Artifact
no bytes
no raw content
```

Exit:

```text
Artifact source contract PASS
AE Slice Gate PASS
```

---

### P9-S13 — WC WorkResult By-Execution Supporting Projection

Goal:

```text
provide supporting lineage without creating an independent WA ingress
```

Add exact route and canonical by-execution lookup:

```text
GET /internal/v1/wa-sources/work-results/{result_id}

GET /internal/v1/wa-sources/work-results/by-execution/{agent_execution_id}
```

Caller:

```text
nex-wa
DEFAULT_SERVICE_SCOPE
work:source:read
```

Projection:

```text
tenant
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

Enforce exact lineage.

Tests:

```text
execution match
tenant mismatch
claim generation mismatch
assignment mismatch
submitted agent mismatch
duplicate result ambiguity fail-closed
no unbounded result payload
```

Exit:

```text
WC remains supporting source owner
no WC→WA event bus added
WC Slice Gate PASS
```

---

### P9-S14 — OA Human Subject Verification Contract

Goal:

```text
verify Human identity without creating a WA identity registry
```

Add/reuse admitted OA route:

```text
POST /internal/v1/identity/subjects:verify-batch
```

Max batch:

```text
50
```

Result:

```text
VERIFIED
SUBJECT_NOT_FOUND
SUBJECT_INACTIVE
TENANT_MEMBERSHIP_MISSING
```

Return bounded revision evidence.

WA client uses signed service token.

Tests:

```text
active
inactive
unknown
wrong tenant
batch boundary 1/50/51
dependency unavailable
wrong scope
```

Exit:

```text
OA remains Human authority
Slice Gate PASS
```

---

### P9-S15 — EOS Project / Historical Membership Verification

Goal:

```text
verify Project attribution without cross-service DB reads
```

Add/reuse:

```text
POST /internal/v1/projects:verify-batch
POST /internal/v1/project-memberships:verify-at
```

Project result:

```text
VERIFIED
PROJECT_NOT_FOUND
PROJECT_INACTIVE
TENANT_MISMATCH
```

Historical membership uses:

```text
tenant_id
project_id
subject_id
occurred_at
```

and returns bounded:

```text
membership_valid
membership_id
role
version
valid_from
valid_to
verification_evidence_hash
```

Tests:

```text
current and historical member
removed after event
joined after event
inactive Project
wrong tenant
dependency outage
```

### P9 Checkpoint Gate #2

After S15:

```text
AE source projections
WC supporting projection
OA verification
EOS verification
signed service boundaries
```

must pass Checkpoint Gate.

---

### P9-S16 — AE Post-Completion Notification

Goal:

```text
notify WA only after authoritative completion barrier
```

IA:

```text
AgentResult SUCCEEDED/PARTIAL
+
WORKSPACE_RESULT ACKNOWLEDGED
+
AgentExecution SUCCEEDED
```

CA/PA/EA:

```text
AgentResult SUCCEEDED/PARTIAL
+
WC_WORK_RESULT ACKNOWLEDGED
+
AgentExecution SUCCEEDED
```

Then:

```text
best-effort POST /internal/v1/evidence-intake
source_type = AE_AGENT_RESULT
```

Notification failure SHALL NOT roll back source completion.

Artifact notification:

```text
READY version
→ AE best-effort notification
```

No mandatory WC notification.

Tests:

```text
pre-ACK no notification
post-ACK one semantic notification
notification timeout source still succeeds
duplicate notification idempotent
restart does not duplicate evidence
```

Exit:

```text
WA receives completed source facts only
AE regression PASS
```

---

### P9-S17 — AgentResult PRIMARY Admission / Completion Barrier

Goal:

```text
turn completed Agent execution into one primary WorkAsset
```

Implement `AeAgentResultSourceAdapter`.

Algorithm:

```text
fetch exact projection
match tenant/ref/hash
require AgentResult SUCCEEDED/PARTIAL
require AgentExecution SUCCEEDED
require correct ResultDelivery ACK
validate Agent type
validate current P9 v1 authority profile
verify Project where applicable
normalize AGENT
create/reuse AgentResult WorkEvidence
derive/reuse Agent WorkAsset
bind PRIMARY
```

Current authority profiles:

```text
IA:
  PROMPT / WORKSPACE_RESULT_ACK

CA/PA/EA:
  CLAIMED_WORKITEM / WC_WORK_RESULT_ACK
```

Unknown future:

```text
AUTONOMOUS_HARNESS
AGENT_INITIATED
...
→ fail closed
→ Controlled Amendment required
```

Typed retry:

```text
WA_AGENT_RESULT_NOT_COMPLETE
```

Tests:

```text
pre-ACK negative
post-ACK positive
IA project null
CA/PA/EA missing claim fail
unknown authority profile fail
PA scheduler-generated claimed work valid
```

Exit:

```text
post-work boundary proven
Slice Gate PASS
```

---

### P9-S18 — WC SUPPORTING Resolution / Source Equivalence

Goal:

```text
attach WC WorkResult to the already authoritative Agent work
without double counting
```

During AgentResult processing:

```text
AgentResult primary
        ↓
WC lookup by execution / claim lineage
        ↓
WorkResult supporting
```

Enforce:

```text
AgentResult.agent_execution_id
==
WorkResult.source_execution_ref
```

plus tenant/Agent/Claim/generation/Assignment match.

Persist:

```text
one Agent WorkAsset
one AgentResult WorkEvidence bound PRIMARY
zero/one WC WorkResult WorkEvidence bound SUPPORTING
```

No independent WC Job.

WC unavailable:

```text
AgentResult Job retryable
```

WC semantic mismatch:

```text
fail closed
```

Tests:

```text
one work / two evidence facts
no duplicate asset
WC unavailable then recovery
lineage mismatch
same WorkResult replay
```

Exit:

```text
double-count rule proven
Slice Gate PASS
```

---

### P9-S19 — Human READY Artifact Admission / Producer Separation

Goal:

```text
prove Human-owned deliverable evidence without inferring Human effort
```

Implement `AeArtifactSourceAdapter`.

Algorithm:

```text
fetch exact Artifact version
require READY
verify tenant/version/hash
resolve Human owner through OA
normalize HUMAN actor
verify Project only when authoritative ProjectRef exists
create/reuse OWNERSHIP_OR_DELIVERABLE_EVIDENCE
derive/reuse HUMAN_OWNED_ARTIFACT WorkAsset
bind PRIMARY
```

If `producer_execution_ref` shows Agent production:

```text
Human ownership evidence
!= Agent production evidence
```

Human owner does not receive Human effort credit.

Project may remain:

```text
null / UNALLOCATED
```

when no authoritative relation exists.

Tests:

```text
Human READY Artifact
inactive owner
Project-member historical valid/invalid
no Project
Agent-produced/Human-owned
no HumanEffortCandidate
```

Exit:

```text
Human source path proven
Slice Gate PASS
```

---

### P9-S20 — Privacy Scopes / Source Authority Closure

Goal:

```text
close authority, privacy and read surface before operational expansion
```

Activate:

```text
work:evidence:read
work:evidence:detail:read
work:evidence:audit:read
```

Rules:

```text
basic read
→ WorkAsset bounded projection

detail
→ individual WorkEvidence / lineage

audit
→ supersession / conflict / replay provenance
```

Human evidence minimum classification:

```text
CONFIDENTIAL
```

Source classification:

```text
preserve or strengthen
never downgrade
```

Also close source correction semantics:

```text
old evidence -> SUPERSEDED / INVALIDATED
new source revision -> new immutable evidence
```

Run protected source/authority acceptance:

```text
Agent pre-ACK negative
Agent post-ACK positive
WC supporting binding
Human Artifact
OA/EOS verification
cross-tenant negative
wrong audience/scope
privacy scope negative
source hash conflict
```

### P9-CA03 — Source / Authority / Privacy Closure

Required:

```text
S11-S20 complete
Checkpoint #2 PASS
actual AE/WC/OA/EOS PostgreSQL evidence where applicable
signed service tokens
no direct DB reads
P9 Full Gate PASS
Statement >= 96%
Branch >= 94%
zero owned residue
```

---

# 13. P9.5 — Optional Contribution Candidate Track

Default status:

```text
DEFERRED / NOT REQUIRED FOR FOUNDATION CLOSURE
```

May be activated only after P9-CA03.

If activated:

### P9-C01 — Candidate Contract / Method Registry

Define:

```text
candidate envelope
method_ref
method_version
evidence_set_hash
confidence
completeness
```

No financial authority.

### P9-C02 — Deterministic Candidate Calculation

Must prove:

```text
no AgentResult/WorkResult/Artifact double counting
no Artifact-count-as-Human-effort shortcut
missing evidence explicit
method version reproducible
```

### P9-C03 — Golden C Candidate Handoff

Provide candidate only.

Golden C remains:

```text
confirmation
0.05-MM finalization
compensation
labor cost
P/L
```

If P9.5 is not activated, Final As-Built records it as DEFERRED.

---

# 14. P9.6 — Operational Maturity

### P9-S21 — Bounded AE Reconciliation / Backfill

Goal:

```text
recover missed non-blocking notifications
```

Add bounded AE listings:

```text
GET /internal/v1/wa-sources/agent-results
GET /internal/v1/wa-sources/artifacts
```

Filters:

```text
created_after
created_before
limit
cursor
```

Return refs/hashes only.

Modes:

```text
operator-triggered
startup-bounded reconciliation
protected maintenance command
```

No general scheduler.

Reconciliation reuses normal intake identity path.

Tests:

```text
missed AgentResult
missed Artifact
bounded cursor
restart
duplicate re-enqueue
```

Exit:

```text
notification loss recoverable
Slice Gate PASS
```

---

### P9-S22 — WC Supporting Re-resolution / Correction Handling

Goal:

```text
ensure reconciled Agent work reconstructs supporting lineage
```

When AE AgentResult is reconciled:

```text
resolve WC WorkResult by execution/claim lineage
bind SUPPORTING once
```

Also implement explicit evidence correction/supersession processing for new
source revisions where current source contract supports correction.

Tests:

```text
AgentResult reconciled + WorkResult supporting
WorkResult same semantics reuse
new source revision new evidence
supersedes link
historical lineage query
```

Exit:

```text
source correction is append-only
Slice Gate PASS
```

---

### P9-S23 — Dead-Letter / Replay / Operator Controls

Goal:

```text
make failed background processing operationally recoverable
```

Use shared:

```text
retry
dead-letter
replay
```

Replay requires:

```text
operator identity
reason
new Job identity
replay lineage
```

Original failed Job remains immutable.

Expose bounded internal operator projections/commands consistent with Platform
patterns.

Tests:

```text
attempt exhaustion
dead-letter
replay unchanged source
replay conflicting source
operator reason required
privacy of error payload
```

Exit:

```text
no hidden manual DB fix required
Slice Gate PASS
```

---

### P9-S24 — Observability / Readiness / Operational Projection

Implement bounded metrics:

```text
queued
running
failed/dead-letter
oldest runnable age
ingest success/failure
hash conflict
evidence reuse
stale recovery
consumer heartbeat
```

No high-cardinality IDs as metric labels.

Structured logs:

```text
trace_id
request_id
job_id
source_type
status
error_code
```

Operational events:

```text
evidence admitted
source conflict
job dead-lettered
stale recovered
reconciliation completed
```

Readiness:

```text
API DB/migrations
consumer DB/tables/heartbeat
```

Tests:

```text
privacy scan
metric label scan
heartbeat loss
readiness failure
```

Exit:

```text
operational visibility complete
Slice Gate PASS
```

---

### P9-S25 — Service Trust / Deployment / Registry Hardening

Goal:

```text
make WA a normal first-class deployed Platform service
```

Close:

```text
NEX_WA_BASE_URL
WA inbound audience
WA→AE token
WA→WC token
WA→OA token
WA→EOS token
AE→WA token
signed-only protected profile
```

No mandatory WC→WA token.

Finalize:

```text
nex-wa-runtime OCI artifact
non-root
read-only FS where applicable
tmpfs
cap_drop ALL
no-new-privileges
managed secrets/TLS
process catalog
```

### P9 Checkpoint Gate #3

After S25:

```text
reconciliation
operations
trust
deployment
```

must pass Checkpoint Gate.

---

### P9-S26 — Load / Backpressure / Concurrent Intake

Goal:

```text
prove PostgreSQL queue is sufficient for Foundation
```

Protected load:

```text
>= 100 concurrent intake requests
>= 2 consumer instances
```

Verify:

```text
one semantic Job per source
one semantic Evidence per source revision
no duplicate WorkAsset
SKIP LOCKED correctness
bounded DB pool use
queue depth behavior
```

Engineering target:

```text
intake p95 <= 500 ms
```

under declared nominal protected environment.

Backpressure:

```text
source authority unchanged
503 only when durable enqueue cannot be guaranteed
```

Exit:

```text
no broker required
Slice Gate PASS
```

---

### P9-S27 — Installed Runtime / Process Topology

Goal:

```text
prove WA runs as part of the installed Platform topology
```

Add:

```text
nex-wa-api
nex-wa-evidence-consumer
nex_wa_dev
managed secrets
health/readiness
runtime image
```

Reuse existing P8 release/deployment framework.

No browser surface required.

Tests:

```text
build image
non-root
entrypoints
start/stop
restart
consumer heartbeat
DB migration current
secret isolation
```

Exit:

```text
installed runtime PASS
Slice Gate PASS
```

---

### P9-S28 — Contract / Negative / Drift Closure

Run canonical validation over all P9 contracts.

Negative set must include:

```text
unsupported source
source hash mismatch
same identity/different hash
cross-tenant
unknown/inactive Human
CA/PA/EA missing Project/Claim
IA Project spoof
Artifact not READY
Artifact version mismatch
WC lineage mismatch
pre-ACK AgentResult
duplicate logical Agent work
stale worker settlement
raw payload
wrong intake scope
basic reader requesting detail
non-WA source projection caller
unknown autonomous authority profile
```

Add producer/consumer parity checks between:

```text
AE projections
WC projection
OA verification
EOS verification
WA adapters
OpenAPI/schema
```

Exit:

```text
contract drift audit PASS
Slice Gate PASS
```

---

### P9-S29 — Protected Canonical Foundation E2E

Run one protected, actual-PostgreSQL, signed-service-trust journey.

Canonical journey:

```text
1. Frozen WA reconciliation already PASS.
2. nex-wa-api / consumer start current.
3. Human-owned READY Artifact exists.
4. CA/PA/EA AgentResult exists while required delivery PENDING.
5. WA does not admit pre-ACK AgentResult as positive evidence.
6. WC result delivery ACK completes AgentExecution.
7. AE notifies completed AgentResult.
8. AE notifies READY Artifact.
9. WA accepts refs/hashes only.
10. PostgreSQL queue claims concurrently.
11. AE source projections re-read.
12. Human owner verified through OA.
13. Project verified through EOS where applicable.
14. AgentResult WorkEvidence is bound PRIMARY.
15. WC WorkResult is resolved by execution/claim lineage.
16. WC WorkResult becomes SUPPORTING evidence.
17. one AgentExecution -> one Agent WorkAsset.
18. Human Artifact -> HUMAN_OWNED_ARTIFACT.
19. no Human effort inferred from ownership.
20. duplicate notifications create no duplicate semantics.
21. source hash conflict fails closed.
22. cross-tenant fails closed.
23. no Approval.
24. no WC Delegation for evidence.
25. no NSL execution.
26. privacy scopes enforce detail/audit boundaries.
27. missed notification reconciliation recovers exact evidence.
28. zero salary/MM/cost/P&L.
29. cleanup leaves zero owned test residue.
```

Record sanitized evidence only.

No raw prompt, token, DB URL, source body, Artifact bytes or private content.

Exit:

```text
P9-E2E-001 PASS
```

---

### P9-S30 — Repository Full Gate / Reliability Closure

Run:

```text
complete repository Full Gate
P9 protected PostgreSQL acceptance
stale-worker fencing fault test
crash-after-local-commit replay
dead-letter/replay
signed service trust
installed runtime acceptance
contract validation
zero residue
```

Coverage:

```text
Statement >= 96%
Branch >= 94%
```

Compare against preceding successful Full Gate.

Any unexplained coverage regression must be investigated even if floor passes.

### P9-CA04 — Foundation Final Acceptance

Required:

```text
S21-S30 complete
Checkpoint #3 PASS
P9 protected E2E PASS
fault/recovery PASS
installed runtime PASS
contracts PASS
Full Gate PASS
coverage PASS
zero residue PASS
```

Foundation implementation is now closed.

---

### P9-S31 — Final As-Built / Handoff Freeze

Create:

```text
P9_Final_AsBuilt_Baseline_and_Next_Phase_Handoff_v1.0.md
```

Record:

```text
exact commit/tree
contract tree
migration heads
service topology
runtime image identity
DB inventory
coverage evidence hashes
protected E2E evidence hashes
fault/recovery evidence
zero-residue evidence
P9.5 status = IMPLEMENTED or DEFERRED
```

Freeze inherited invariants:

```text
WA is post-work
WA not Scheduler
no cross-service DB
no Approval for evidence
no WC Delegation for evidence
no NSL Foundation dependency
Agent completion barrier
source equivalence
stale-worker fencing
privacy scope separation
future autonomous authority profiles fail closed unless amended
```

Next phase/handoff is determined only after this As-Built closure.

---

# 15. Slice-to-Phase Map

| Phase | Slices | Objective |
|---|---|---|
| P9-CA01 | pre-S01 | Frozen WA reconciliation / coding entry |
| P9.2 | S01–S10 | Core owner-local evidence service |
| P9-CA02 | after S10 | Core Foundation closure |
| P9.3 | S11–S13, S16–S18 | Source projections / source intake / equivalence |
| P9.4 | S14–S15, S19–S20 | Identity / Project / privacy / authority |
| P9-CA03 | after S20 | Source + authority closure |
| P9.5 | optional C01–C03 | Contribution candidates |
| P9.6 | S21–S28 | Reconciliation / operations / deployment |
| P9.7 | S29–S31 | Protected E2E / Full Gate / Final As-Built |
| P9-CA04 | after S30 | Final Foundation acceptance |

---

# 16. Checkpoint / Full Gate Cadence

```text
S01
S02
S03
S04
S05  → Checkpoint Gate #1

S06
S07
S08
S09
S10  → Full Gate / P9-CA02

S11
S12
S13
S14
S15  → Checkpoint Gate #2

S16
S17
S18
S19
S20  → Full Gate / P9-CA03

S21
S22
S23
S24
S25  → Checkpoint Gate #3

S26
S27
S28
S29
S30  → Full Gate / P9-CA04

S31  → documentation/freeze verification
```

Escalate early if risk warrants.

---

# 17. Protected Test Matrix

## P9-E2E-01 — Human Artifact

```text
READY Artifact
→ OA Human verify
→ optional EOS Project verify
→ WorkEvidence PRIMARY
→ HUMAN_OWNED_ARTIFACT
```

Negative:

```text
inactive subject
not READY
hash mismatch
ownership != effort
```

---

## P9-E2E-02 — Agent Pre-ACK Negative

```text
AgentResult persisted
required delivery PENDING
→ WA_AGENT_RESULT_NOT_COMPLETE
→ no positive WorkEvidence
```

---

## P9-E2E-03 — Agent Post-ACK + WC Supporting

```text
required delivery ACK
AgentExecution SUCCEEDED
→ AgentResult PRIMARY
→ WC lookup
→ WorkResult SUPPORTING
→ one WorkAsset
```

---

## P9-E2E-04 — IA Project Neutrality

```text
IA text mentions project
no authoritative ProjectRef
→ project_ref = null
```

---

## P9-E2E-05 — Duplicate Intake

```text
10 same intake requests
→ 1 semantic Job
→ 1 WorkEvidence
→ 1 WorkAsset
```

---

## P9-E2E-06 — Concurrent Intake / Consumers

```text
100 concurrent notifications
2+ consumers
→ SKIP LOCKED
→ no duplicate semantics
```

---

## P9-E2E-07 — Crash After Local Commit

```text
Evidence/Asset commit
worker crash
Job remains RUNNING
recovery
same Evidence/Asset reused
Job succeeds
```

---

## P9-E2E-08 — Stale Worker Fencing

```text
Worker A claim
A stale
recovery CAS
Worker B claim
A wakes
A settlement rejected
B completes
```

---

## P9-E2E-09 — Source Conflict

```text
same source identity
different source hash
→ typed conflict
→ no overwrite
```

---

## P9-E2E-10 — Authorization / Tenant

```text
wrong audience
wrong caller
wrong scope
cross-tenant projection
→ fail closed
```

---

## P9-E2E-11 — Reconciliation

```text
notification intentionally skipped
bounded reconciliation
→ exact source re-enqueued
→ one semantic evidence
```

---

## P9-E2E-12 — Supersession

```text
old source revision
→ ACTIVE evidence

corrected source revision
→ new evidence
→ old SUPERSEDED
→ history preserved
```

---

## P9-E2E-13 — Privacy Scopes

```text
basic read
→ no detailed Human lineage

detail scope
→ bounded WorkEvidence refs/hashes

audit scope
→ bounded replay/conflict/supersession provenance
```

---

## P9-E2E-14 — Unknown Autonomous PA Authority

```text
PA AgentResult
execution authority = unknown autonomous profile
→ fail closed
→ no WorkEvidence
```

This proves future compatibility without activating autonomous execution in P9.

---

## P9-E2E-15 — Zero Residue

After protected acceptance:

```text
WA test rows = 0
temporary source fixtures = 0 where owned by test
temporary service trust = 0
runtime Jobs = 0 terminal test residue as defined by cleanup contract
```

Historical immutable migration/evidence reports remain outside runtime DB
residue rules.

---

# 18. Slice Definition of Done

Every production Slice is complete only when:

```text
requirements mapped
source structure reviewed
implementation bounded
unit tests added
boundary/robustness/worst-case cases added where applicable
owning-service regression PASS
P9 Slice Gate PASS
coverage floor satisfied
protected evidence run when claimed
git diff --check PASS
documentation/As-Built note updated
commit synchronized
```

No "code complete, tests later" Slice is accepted.

---

# 19. P9.2 Definition of Done

P9.2 closes only when:

```text
nex-wa first-class service exists
WA DB current
service_jobs/heartbeat current
WorkEvidence implemented
WorkAsset implemented
binding implemented
local transaction implemented
intake contract implemented
API durable enqueue implemented
consumer lifecycle implemented
stale recovery fenced
basic exact reads implemented
actual PostgreSQL PASS
Full Gate PASS
```

It does not require real P8 source integration yet.

---

# 20. P9.3 / P9.4 Definition of Done

Source/authority integration closes only when:

```text
AE AgentResult completion-aware projection
AE Artifact safe projection
WC by-execution supporting projection
OA subject verification
EOS Project/historical membership verification
post-completion AE notification
AgentResult PRIMARY admission
WC WorkResult SUPPORTING resolution
Human Artifact admission
source equivalence
double-count protection
privacy scopes
classification
supersession
signed service trust
actual PostgreSQL acceptance
Full Gate PASS
```

---

# 21. P9.6 Definition of Done

Operational maturity closes when:

```text
missed notification reconciliation
supporting re-resolution
dead-letter/replay
operator controls
observability
readiness
load/backpressure
installed runtime
contract drift closure
security negative closure
```

No external broker is required.

---

# 22. P9.7 Definition of Done

Foundation final closure requires:

```text
P9-CA01 PASS
P9-CA02 PASS
P9-CA03 PASS
P9-CA04 PASS
P9-E2E-001 canonical journey PASS
P9-E2E-01..15 evidence complete
Full Gate PASS
Statement >= 96%
Branch >= 94%
zero residue
Final As-Built frozen
```

P9.5 candidate implementation is not a prerequisite.

---

# 23. Expected Source Surface

Likely new WA owner source:

```text
services/nex-wa/nex_wa/
  __init__.py
  main.py
  app.py
  config.py
  persistence.py
  work_evidence.py
  work_assets.py
  source_admission.py
  source_adapters.py
  source_clients.py
  evidence_jobs.py
  evidence_worker.py
  recovery.py
  queries.py
  auth.py
  errors.py
```

Exact files are not normative; source structure should be refactored when a
smaller/clearer package boundary exists.

Cross-service additive source likely includes:

```text
AE
  WA AgentResult projection
  WA Artifact projection
  post-completion notification
  reconciliation listings

WC
  WorkResult exact projection
  WorkResult by-execution projection

OA
  subject verify contract

EOS
  Project verify
  historical ProjectMember verify

_shared
  nex-wa service vocabulary / endpoint / observability registration
  fenced common Job settlement only if backward-compatible extraction is justified

deployment
  nex-wa runtime artifact
  process topology
  service trust / secrets / readiness

database
  nex-wa migration history
```

---

# 24. Shared Runtime Change Rule

P9 SHALL reuse shared runtime.

Do not modify shared JobQueue merely because WA needs a feature if that feature
is WA-specific.

For stale settlement fencing:

```text
prefer backward-compatible shared CAS primitive
only if semantics are generally correct for all service_jobs users
```

Otherwise:

```text
compose WA-specific fenced settlement adapter
on top of common persistence
```

Any shared-runtime modification triggers:

```text
early Checkpoint/Full Gate
cross-service regression
```

---

# 25. PA Scheduler / Harness Forward Compatibility

Current P9 does not implement Scheduler or autonomous Agent authority.

Current accepted PA paths:

```text
Human/Agent delegation
→ WC WorkItem
→ Claim
→ CLAIMED_WORKITEM
→ PA AgentExecution

Future Schedule
→ Occurrence
→ WC WorkItem
→ Claim
→ CLAIMED_WORKITEM
→ PA AgentExecution
```

Both produce normal P9 Agent WorkAsset after completion.

Future self-starting PA Harness may eventually introduce a new authority profile.

P9 Foundation does not block that future, but does not authorize it.

```text
AUTONOMOUS_HARNESS / AGENT_INITIATED
→ unknown in P9 v1
→ fail closed
→ Controlled Amendment
```

WA's permanent abstraction is:

```text
authoritative execution authority
+
authoritative completion evidence
```

not:

```text
WC Claim forever
```

---

# 26. Explicit Non-Goals for Slice Planning

No Slice may introduce the following merely to simplify P9:

```text
Kafka
RabbitMQ
NATS
Redis Streams
Celery as a second queue authority
new Agent RuntimeJob type
WA scheduler
general workflow engine
new Human identity registry
new Project master
new approval state
WA-specific NSL Skill
Work Asset Skill Pack
LLM evidence authority
Human effort from Artifact count
Agent monetary cost
salary/payroll fields
Project P/L
```

If a Slice starts requiring one of these:

```text
STOP
→ architecture review
```

---

# 27. Recommended First Coding Batch

After P9-CA01 PASS:

```text
P9-S01
P9-S02
P9-S03
P9-S04
P9-S05
→ Checkpoint Gate #1
```

This batch proves the most important architectural property before any
cross-service integration:

> NeX-WA can independently own immutable, idempotent WorkEvidence and bounded
> WorkAsset state on its own PostgreSQL boundary.

Only after that should source integration begin.

---

# 28. Recommended Second Coding Batch

```text
P9-S06
P9-S07
P9-S08
P9-S09
P9-S10
→ P9-CA02 / Full Gate
```

This batch proves:

```text
durable background intake
worker lifecycle
fenced crash recovery
basic query/readiness
```

before touching P8 owner services.

---

# 29. Recommended Third Coding Batch

```text
P9-S11
P9-S12
P9-S13
P9-S14
P9-S15
→ Checkpoint Gate #2
```

This batch establishes source owner projections and authority verification
without yet changing semantic completion behavior.

---

# 30. Recommended Fourth Coding Batch

```text
P9-S16
P9-S17
P9-S18
P9-S19
P9-S20
→ P9-CA03 / Full Gate
```

This is the key semantic batch.

It closes:

```text
post-completion admission
PRIMARY / SUPPORTING equivalence
Human Artifact evidence
future Agent authority profile guard
privacy
```

---

# 31. Recommended Final Operations Batch

```text
P9-S21
...
P9-S30
→ P9-CA04
```

Then:

```text
P9-S31
→ Final As-Built Freeze
```

---

# 32. Final Plan Decision

The implementation sequence is intentionally conservative:

```text
reconcile Frozen authority first
        ↓
build WA as an independent local evidence domain
        ↓
prove queue/idempotency/recovery locally
        ↓
integrate P8 sources through narrow owner APIs
        ↓
prove completion barrier / source equivalence
        ↓
add identity / Project / privacy controls
        ↓
add reconciliation / operations / deployment
        ↓
protected E2E / Full Gate
        ↓
Final As-Built
```

The central implementation rule is:

> **Do not build a larger P9 because future PA autonomy, Golden C, scheduling,
> Skill Packs or richer analytics are desirable. Build only the NeX-WA
> Foundation that those future capabilities can safely depend on.**
