# P9 — NeX-WA (Work Asset)
# Contract Closure v1.1

**Status:** DESIGN CLOSURE / P9 SRS+PLAN ENTRY AUTHORIZED / P9.2 CODING GATED BY FROZEN-WA RECONCILIATION
**Phase:** P9 — NeX-WA / Work Asset Foundation
**Platform:** NeX Platform v2.1
**Predecessor:** `P9_NeX_WA_Pre_Architecture_Decision_v1.2.md`
**Source Audit:** `P9_NeX_WA_Source_Audit_and_Gap_Analysis_v1.0.md`
**P8 Handoff:** `P8_Final_AsBuilt_Baseline_and_P9_Handoff_v1.2.md`
**Repository:** `nurigitdev/2607_nex_platform`
**Branch:** `transition/p4-agent-runtime-foundation`
**Audited HEAD:** `c3a1ea907387b67fe7a63407e4d668d13b1be8e7`
**Audited Tree:** `7df03a1ff280baefbda4e56b1ff0e0818ef0bde3`
**NSL Baseline:** v0.2.1, but P9 Foundation does not require NSL
**Date:** 2026-10-27
**Revision Note:** v1.1 adds authoritative completion-barrier admission for AgentResult, WC supporting-evidence discovery by exact execution lineage, fenced stale-RUNNING recovery, and a mandatory Frozen WA reconciliation gate before P9.2 domain coding.
**Next:** P9 SRS / Implementation Slice Plan

---

# 1. Purpose

This document closes the implementation contracts required to begin P9
NeX-WA Foundation.

It converts the P9 Pre-Architecture and Source Audit into one implementation
boundary.

The goal is deliberately small:

```text
Authoritative source exists
        ↓
source owner sends/admits exact reference
        ↓
NeX-WA queues background intake
        ↓
worker verifies source deterministically
        ↓
immutable/idempotent WorkEvidence
        ↓
bounded WorkAsset
```

P9 Foundation is not another workflow engine.

---

# 2. Closure Statement

The following architecture is approved:

```text
                  P8 Authoritative Sources
        ┌────────────────┬────────────────┐
        │                │                │
  AE AgentResult    AE Artifact      WC WorkResult
        │                │          [supporting only]
        └───────┬────────┘                │
                │ exact source ref        │
                ▼                         │
          ┌───────────────┐               │
          │  nex-wa-api   │◄──────────────┘
          │ intake/admit  │
          └───────┬───────┘
                  │
                  ▼
          ┌───────────────┐
          │ service_jobs  │
          │ WA_EVIDENCE_  │
          │ INGEST        │
          └───────┬───────┘
                  │ claim
                  ▼
   ┌──────────────────────────────┐
   │ nex-wa-evidence-consumer     │
   │ source / actor / project     │
   │ hash / idempotency verify    │
   └──────────────┬───────────────┘
                  │
                  ▼
        ┌─────────────────────┐
        │   NeX-WA PostgreSQL │
        │ WorkEvidence        │
        │ WorkAsset           │
        │ Asset↔Evidence      │
        └─────────────────────┘
```

No Human Approval, WC Delegation, NSL Skill, scheduler, Kafka, RabbitMQ, NATS,
or Redis Streams is required for this Foundation path.

---

# 3. Authority Order

The implementation SHALL follow this order of authority:

```text
1. Current P8 executable source and frozen P8 As-Built invariants
2. P9 Contract Closure v1.0
3. P9 Pre-Architecture Decision v1.2
4. P9 Source Audit v1.0
5. Earlier Work Asset / Human Effort legacy references
```

A lower item SHALL NOT silently override a higher item.

---

# 4. Treatment of Legacy Frozen Work Asset References

The repository contains the legacy/frozen reference artifacts:

```text
23_NeX_Work_Asset_Human_Effort_and_Labor_Allocation_Design_v2.0.docx

23_NeX_Work_Asset_Human_Effort_and_Labor_Allocation_Implementation_Contracts_v2.0.zip
```

Their binary existence is source-backed.

Their full internal text was not materialized as part of the Source Audit.

Therefore this Closure SHALL NOT invent or silently import requirements from
those binary files.

If later materialization reveals a real contradiction with this Contract
Closure:

```text
do not silently merge
do not silently rewrite current contracts
```

Instead:

```text
P9 Controlled Amendment
```

is required.

This rule allows P9 SRS and implementation planning to proceed without pretending
that unavailable legacy text has been reviewed.

## 4.1 Frozen WA Reconciliation Gate

The following Frozen/reference artifacts SHALL be materialized and reconciled
before P9.2 domain implementation begins:

```text
23_NeX_Work_Asset_Human_Effort_and_Labor_Allocation_Design_v2.0.docx
23_NeX_Work_Asset_Human_Effort_and_Labor_Allocation_Implementation_Contracts_v2.0.zip
```

The required reconciliation record SHALL classify each material finding as:

```text
COMPATIBLE
ADDITIVE / INCORPORATE
CONFLICT / CONTROLLED AMENDMENT REQUIRED
NOT APPLICABLE TO P9 FOUNDATION
```

The reconciliation SHALL compare the materialized Frozen/reference semantics
against:

```text
P8 Final As-Built v1.2 + merged P8-DEMO baseline
P9 Pre-Architecture Decision v1.2
P9 Source Audit v1.0
P9 Contract Closure v1.1
```

P9 SRS and Implementation Slice Plan MAY proceed before this reconciliation is
complete.

However:

```text
P9.2 production domain coding
= BLOCKED
until Frozen WA reconciliation is recorded.
```

If the materialized Frozen/reference documents contradict a closed ownership,
SoR, identity, approval, result-publication, WorkEvidence or WorkAsset semantic
in this Closure, implementation SHALL stop and a P9 Controlled Amendment SHALL
be performed before coding continues.

---

# 5. NeX-WA Service Ownership

A new first-class Platform service is approved:

```text
service_id = nex-wa
```

NeX-WA owns only:

```text
WorkEvidence
WorkAsset
WorkAsset↔Evidence binding
evidence source admission
evidence source idempotency
evidence provenance
WA queries
later contribution candidates
```

---

# 6. NeX-WA Does Not Own

NeX-WA SHALL NOT own:

```text
Human identity                -> OA
Agent identity/execution      -> AE
WorkItem/Claim/Delegation     -> WC
Project/ProjectMember         -> EOS
Artifact bytes                -> AE / object storage owner
Compensation/Payroll          -> Golden C / EOS
Project Labor Cost            -> Golden C / EOS
Project P/L                   -> Golden C / EOS
```

---

# 7. Runtime Process Contract

Initial P9 runtime is exactly two WA-owned process types:

```text
nex-wa-api
nex-wa-evidence-consumer
```

No separate:

```text
WA scheduler
WA dispatcher service
WA orchestration service
```

is authorized by this Closure.

---

# 8. Deployment Artifact Contract

The first-class runtime artifact SHALL be:

```text
artifact_id = nex-wa-runtime
owner       = nex-wa
kind        = python-service
```

The runtime image MAY host both:

```text
nex-wa-api
nex-wa-evidence-consumer
```

through different entrypoints.

---

# 9. PostgreSQL Ownership Contract

NeX-WA SHALL own an independent PostgreSQL boundary.

Expected environments:

```text
NEX_WA_DATABASE_URL
NEX_WA_TEST_DATABASE_URL
```

Expected names:

```text
nex_wa_dev
nex_wa_test
```

Expected owner role:

```text
nex_wa_user
```

Exact local operator/bootstrap conventions SHALL follow the current Platform
PostgreSQL patterns.

---

# 10. No Cross-Service Database Reads

NeX-WA SHALL NOT query:

```text
nex_ae database
nex_wc database
nex_oa database
nex_eos database
```

directly.

All source verification uses:

```text
service-to-service API
or
an explicitly admitted source projection contract
```

No cross-database foreign key is permitted.

---

# 11. General JobQueue Contract

P9 SHALL reuse:

```text
nex_runtime.jobs
SqlAlchemyJobQueue
service_jobs
WorkerRunner
WorkerHeartbeatEmitter
```

The WA queue is owner-local.

---

# 12. AE RuntimeJob Separation

P9 SHALL NOT use:

```text
ae_runtime_job
ae_runtime_job_attempt
```

for evidence ingestion.

The accepted separation remains:

```text
service_jobs
= general service background work

ae_runtime_job
= AgentExecution / ExecutableStep progression
```

---

# 13. Initial WA Job Type

The initial P9 Foundation SHALL define exactly one business Job type:

```text
WA_EVIDENCE_INGEST
```

Additional WA Job types require a later explicit requirement.

---

# 14. Job State Vocabulary

P9 SHALL reuse `common_job.v1` states:

```text
QUEUED
RUNNING
SUCCEEDED
FAILED
CANCELLED
```

WA SHALL NOT add approval states to JobQueue.

---

# 15. Job Payload Rule

`WA_EVIDENCE_INGEST` payload SHALL contain references only.

Minimum logical payload:

```text
source_type
source_ref
source_revision_ref
source_hash
```

Optional bounded routing/trace metadata MAY include:

```text
tenant_id
trace_id
request_id
correlation_ref
```

The payload SHALL NOT contain:

```text
raw prompt
raw document body
Artifact bytes
credentials
access token
password
salary
payroll detail
unbounded source payload
```

---

# 16. Queue Idempotency Key

Queue idempotency SHALL bind:

```text
tenant_id
source_type
source_ref
source_revision_ref
```

The serialized/canonical projection SHALL be hashed to derive a bounded
idempotency key.

Equivalent source intake SHALL return/reuse the existing Job.

---

# 17. Job Retry Policy

Initial WA evidence Job policy is:

```text
max_attempts             = 5
retryable                = true

initial retry delay      = 30 seconds
maximum retry delay      = 900 seconds
backoff multiplier       = 2.0
```

These values align with the existing shared JobQueue model.

Policy changes require versioned runtime configuration.

---

# 18. Dead-Letter Contract

After retry exhaustion:

```text
status = FAILED
error.dead_lettered = true
```

Dead-letter replay requires:

```text
explicit operator action
operator identity
reason
new replay Job identity
replay lineage
```

The original failed Job remains immutable history.

---

# 19. Concurrent Claim Contract

PostgreSQL worker claim SHALL use the existing:

```text
FOR UPDATE SKIP LOCKED
```

shared JobQueue behavior.

This allows multiple `nex-wa-evidence-consumer` instances.

---

# 20. Worker Scaling Contract

Initial deployment MAY run:

```text
1 consumer
```

Horizontal scale MAY later run:

```text
N consumers
```

without changing the intake API or evidence identity.

---

# 21. Shared JobQueue Crash-Recovery Gap

Current shared `service_jobs` supports:

```text
claim
retry
dead-letter
replay
```

but does not provide the same lease-expiry ledger as AE RuntimeJob.

A worker process can fail after a Job becomes `RUNNING`.

This Closure explicitly closes that gap for WA.

---

# 22. Stale RUNNING Recovery Contract

P9 SHALL implement a bounded WA recovery step.

A WA `RUNNING` Job may be considered stale only when:

```text
job_type = WA_EVIDENCE_INGEST
status = RUNNING
locked_at < recovery_cutoff
```

and the owning worker heartbeat is absent/stale or the worker identity is no
longer active according to the WA runtime recovery policy.

Recovery SHALL:

```text
RUNNING stale Job
        ↓
fenced / compare-and-set recovery
        ↓
requeue if attempts remain
        or
dead-letter if attempts exhausted
```

The recovery transition SHALL verify the expected ownership state, including
the applicable equivalent of:

```text
job_id
expected status = RUNNING
expected locked_by
expected locked_at / claim epoch
```

A blind update based only on `job_id` or age is not sufficient.

Once recovery succeeds, the previous worker loses settlement authority for that
claim. A stale worker that later wakes up SHALL NOT be allowed to complete,
fail, retry, or otherwise settle the recovered Job using its former ownership.

The exact implementation MAY use a lock generation, claim token, or an
equivalent compare-and-set guard, but the fencing semantic is mandatory.

It SHALL NOT create a second semantic evidence record.

---

# 23. Recovery Safety

Stale Job recovery is safe because WorkEvidence has an independent semantic
idempotency boundary.

Required crash sequence:

```text
WorkEvidence commits
        ↓
worker crashes before Job completion
        ↓
RUNNING Job becomes stale
        ↓
Job is recovered/requeued
        ↓
same WorkEvidence identity is found
        ↓
existing evidence reused
        ↓
Job becomes SUCCEEDED
```

---

# 24. Worker Heartbeat Contract

P9 SHALL extend the shared service vocabulary to admit:

```text
service_id = nex-wa
```

Worker type:

```text
wa.evidence_consumer
```

or an equivalent versioned bounded identifier.

Heartbeat states reuse:

```text
STARTING
IDLE
BUSY
STOPPING
STOPPED
ERROR
```

---

# 25. Runtime Readiness Contract

`nex-wa-api` SHALL expose normal API readiness.

`nex-wa-evidence-consumer` SHALL prove readiness through:

```text
PostgreSQL connectivity
required WA tables current
service_jobs current
worker heartbeat current
```

---

# 26. Evidence Admission Is Not Approval

The central P9 Foundation rule is frozen:

```text
Evidence Admission
!=
Business Approval
```

Authoritative evidence registration is background processing.

---

# 27. Approval-Free Intake

Ordinary system-generated source evidence SHALL NOT require:

```text
Artifact creator approval
manager approval
WC Approval WorkItem
Human Gate
NSL approval
```

before WorkEvidence is admitted.

---

# 28. Approval-Free Does Not Mean Uncontrolled

Before evidence persistence, the worker SHALL verify applicable:

```text
source identity
source revision/hash
tenant
actor
Project
classification
source semantic consistency
idempotency identity
```

Invalid evidence fails closed.

---

# 29. Source Work State Is Independent

WA failure SHALL NOT retroactively change:

```text
AgentResult
WorkResult
Artifact
Project
```

business/source state.

WA is a projection/evidence domain.

---

# 30. WA Backpressure Rule

If WA is overloaded or unavailable:

```text
source business fact remains authoritative
WA intake is delayed/retried
```

A valid AgentResult or Artifact does not become invalid because WA processing
is delayed.

---

# 31. Initial Source Set

P9 Foundation closes the initial source set as:

```text
PRIMARY:
AE_AGENT_RESULT
AE_ARTIFACT

SUPPORTING:
WC_WORK_RESULT
```

No other source is required for P9.2/P9.3 Foundation closure.

---

# 32. Sources Deferred

Deferred from initial Foundation:

```text
EOS BusinessOperation event ingestion
CX generation/retrieval events
MO telemetry
service logs
generic operational events
manual/import evidence
external systems
```

They may be added later by Controlled Amendment or later P9 slices.

---

# 33. AE AgentResult Source Contract

An admitted `AE_AGENT_RESULT` source SHALL provide a safe projection including:

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
```

The projection SHALL additionally expose enough completion-barrier metadata to
prove that the authoritative upstream result-publication boundary has closed:

```text
agent_execution_state
required_delivery_target_type
required_delivery_state
```

Optional bounded completion metadata MAY include the exact delivery identity and
acknowledgement timestamp/ref.

Only bounded refs/hashes are required.

---

# 34. AgentResult Status and Completion-Barrier Admission

`AgentResult.status` alone is not sufficient for positive post-work admission.

Initial WA positive admission requires all of:

```text
AgentResult.status = SUCCEEDED | PARTIAL
AgentExecution.state = SUCCEEDED
required ResultDelivery.state = ACKNOWLEDGED
```

The required delivery target SHALL match the authoritative execution profile:

```text
IA
→ WORKSPACE_RESULT

CA / PA / EA
→ WC_WORK_RESULT
```

For `CA / PA / EA`, the admitted projection SHALL also preserve the current
WorkItem / Claim / claim-generation / Assignment lineage required by the
completed background execution.

Therefore:

```text
AgentResult persisted
but required delivery not ACKNOWLEDGED
→ NOT positive WA post-work evidence yet
```

Such a source MAY remain pending/retryable for WA admission, but WA SHALL NOT
reinterpret it as completed work.

The following AgentResult states MAY be stored later as operational history but
SHALL NOT create positive contribution evidence in Foundation:

```text
BLOCKED
FAILED
CANCELLED
```

This rule preserves the P4-P8 result-publication completion boundary and keeps
WA strictly post-work.

---

# 35. Agent Actor Contract

For AgentResult:

```text
actor_type = AGENT
actor_ref  = agent_id
```

The source `agent_type` SHALL be preserved as:

```text
agent_type_snapshot = IA | CA | PA | EA
```

It is provenance/classification, not a separate WA identity domain.

---

# 36. Background Agent Project Attribution

For:

```text
CA
PA
EA
```

the authoritative AgentResult already requires:

```text
project_id
WC claim lineage
```

P9 SHALL preserve those references.

WA SHALL not invent a different Project.

---

# 37. IA Project Attribution

Current IA AgentResult is Project-neutral.

Therefore:

```text
IA text mentions Project-X
```

does NOT establish:

```text
project_ref = Project-X
```

A Project-scoped IA WorkAsset requires an independent authoritative Project
reference.

Without it:

```text
project_ref = null
```

is valid.

---

# 38. AE Artifact Source Contract

An admitted `AE_ARTIFACT` source SHALL reference an exact rendered/versioned
Artifact state.

The source projection SHALL include at least:

```text
tenant_id
artifact_id
artifact_version_id
artifact_status
owner_actor_ref
workspace_ref
artifact_content_hash
source_content_hash
created_at
classification / retention-relevant projection
```

Only:

```text
artifact_status = READY
```

is admitted as normal positive Foundation evidence.

---

# 39. Artifact Version Identity

Artifact evidence identity SHALL be version-specific.

The canonical source revision is:

```text
artifact_version_id
```

and source semantic integrity SHALL bind:

```text
artifact_content_hash
```

A later Artifact version creates a new WorkEvidence source identity.

---

# 40. Human Actor Normalization

When an Artifact `owner_actor_ref` represents a user:

```text
actor_type = HUMAN
```

WA SHALL resolve/verify the actor against OA.

The canonical persisted Human actor is:

```text
actor_ref = OA subject_id
```

Display employee number/name is not WA identity authority.

---

# 41. Artifact Ownership Is Not Human Effort Proof

This Closure freezes an important limitation:

```text
Artifact owner
!=
proof of Human effort quantity
```

AE Artifact can prove:

```text
Human ownership/responsibility
deliverable association
Artifact existence
```

It does NOT by itself prove:

```text
hours worked
MM
relative Project contribution
performance
```

---

# 42. Human Evidence Kind

Initial Human Artifact evidence SHALL be classified as:

```text
OWNERSHIP_OR_DELIVERABLE_EVIDENCE
```

or an equivalent bounded contract term.

It SHALL NOT be automatically classified as:

```text
HUMAN_EFFORT
```

without additional evidence.

---

# 43. WC WorkResult Source Role

Current WC WorkResult is Agent-only.

Therefore in P9 Foundation:

```text
WC_WORK_RESULT
```

is not an independent Human source.

It is supporting evidence for background Agent lineage.

---

# 44. WC WorkResult Supporting Projection

The supporting projection SHALL include at least:

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

The worker SHALL only attach it when lineage matches the primary Agent work.

---

# 45. Source Equivalence — AgentResult and WorkResult

For background Agent work:

```text
AE AgentResult.agent_execution_id
==
WC WorkResult.source_execution_ref
```

is the canonical linkage.

When equal and tenant/Agent lineage also matches:

```text
AgentResult = PRIMARY evidence
WorkResult  = SUPPORTING evidence
```

Both SHALL attach to one WorkAsset.

They SHALL NOT create two contribution units.

---

# 46. Source Equivalence — AgentResult and Artifact

If an AgentResult references an Artifact:

```text
Artifact evidence
```

MAY attach to the same Agent WorkAsset as supporting evidence.

An Artifact reference SHALL NOT automatically create a second contribution
unit merely because it is also independently discoverable.

---

# 47. Human-owned Artifact Produced by Agent

The current Artifact owner model can represent the user who owns the Artifact,
while an Agent may have produced it.

Therefore P9 SHALL distinguish:

```text
ownership evidence
production/execution evidence
```

If AgentResult lineage proves the Agent produced the Artifact:

```text
AgentResult = execution evidence
Artifact    = deliverable/ownership supporting evidence
```

The Human owner SHALL NOT automatically receive Human effort credit from that
ownership fact.

---

# 48. Initial WorkAsset Types

P9 Foundation closes two initial logical WorkAsset types:

```text
AGENT_EXECUTION_RESULT
HUMAN_OWNED_ARTIFACT
```

These names are logical contract identities; physical enum naming may be
normalized in SRS as long as semantics remain unchanged.

---

# 49. AGENT_EXECUTION_RESULT Identity

One Agent WorkAsset SHALL be keyed by:

```text
tenant_id
agent_execution_id
```

The deterministic WorkAsset ID SHOULD derive from those values.

One AgentExecution produces at most one semantic Agent WorkAsset.

---

# 50. HUMAN_OWNED_ARTIFACT Identity

One Human-owned Artifact WorkAsset SHALL be keyed by:

```text
tenant_id
artifact_id
artifact_version_id
```

A new Artifact version may create a new versioned WorkAsset/evidence
projection according to SRS.

---

# 51. WorkEvidence Physical Contract

P9 SHALL create:

```text
wa_work_evidence
```

Minimum logical columns:

```text
tenant_id
work_evidence_id

source_owner
source_type
source_ref
source_revision_ref
source_hash

evidence_role
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

Exact SQL types and identifier lengths are SRS scope.

---

# 52. WorkEvidence Status

Initial semantic states:

```text
ACTIVE
SUPERSEDED
INVALIDATED
```

These are evidence lifecycle states.

They are NOT approval states.

---

# 53. WorkEvidence Source Uniqueness

P9 SHALL enforce a unique source identity equivalent to:

```text
tenant_id
source_type
source_ref
source_revision_ref
```

One exact source revision creates at most one ACTIVE semantic WorkEvidence.

---

# 54. WorkEvidence Conflict Rule

```text
same source identity
+ same source hash
→ existing WorkEvidence reused

same source identity
+ different source hash
→ EVIDENCE_SOURCE_CONFLICT
```

A conflict SHALL NOT silently overwrite evidence.

---

# 55. WorkEvidence Hash

`evidence_hash` SHALL bind at least:

```text
tenant
source identity
source hash
evidence role/kind
actor identity
agent type snapshot
Project ref
occurred_at
classification
supersession ref
```

using canonical semantic hashing.

---

# 56. WorkAsset Physical Contract

P9 SHALL create:

```text
wa_work_asset
```

Minimum logical columns:

```text
tenant_id
work_asset_id

asset_type

actor_type
actor_ref
agent_type_snapshot

project_ref

primary_evidence_id

occurred_at
classification

asset_status
asset_hash
version

created_at
updated_at
```

---

# 57. WorkAsset Status

Initial states:

```text
ACTIVE
SUPERSEDED
INVALIDATED
```

No business approval state is required.

---

# 58. WorkAsset Evidence Binding

P9 SHALL create a binding that allows one WorkAsset to contain multiple
evidence facts.

Logical relation:

```text
wa_work_asset_evidence
────────────────────────────────
tenant_id
work_asset_id
work_evidence_id
binding_role
created_at
```

Binding role:

```text
PRIMARY
SUPPORTING
```

This relation is required to prevent double-counting while preserving lineage.

---

# 59. One Primary Evidence Rule

Each WorkAsset SHALL have exactly one PRIMARY evidence identity.

Supporting evidence MAY be zero or more.

---

# 60. WorkEvidence Is Immutable

Once ACTIVE WorkEvidence is admitted, its source identity/hash SHALL NOT be
rewritten in place.

Correction uses:

```text
new WorkEvidence
+
supersedes_evidence_id
```

or explicit invalidation.

---

# 61. Source Correction Contract

Correction flow:

```text
existing evidence
        ↓
SUPERSEDED / INVALIDATED
        ↓
new source revision
        ↓
new WorkEvidence
        ↓
WorkAsset projection/version updated
```

Historical lineage remains queryable.

---

# 62. Atomic Local Transaction

For one `WA_EVIDENCE_INGEST` execution, the following WA-local mutations SHOULD
commit in one PostgreSQL transaction where applicable:

```text
WorkEvidence create/reuse
WorkAsset create/update
WorkAsset↔Evidence binding
```

Job completion occurs after the local transaction commits.

This ordering is intentional.

---

# 63. Crash After Local Commit

If the local transaction commits but the worker crashes before Job completion:

```text
retry/recovery
→ evidence uniqueness
→ existing evidence/asset reused
→ Job completes
```

No duplicate WorkEvidence/WorkAsset is permitted.

---

# 64. Source Verification API Boundary

P9 SHALL add or reuse narrow service-to-service source projection APIs.

WA SHALL NOT use browser-facing/user-facing payloads as its authoritative
source contract merely because they already exist.

---

# 65. AE AgentResult WA Source Projection

A narrow AE internal projection is authorized.

Recommended logical route:

```text
GET /internal/v1/wa-sources/agent-results/{result_id}
```

Caller:

```text
nex-wa
```

Required service token audience/scope SHALL be versioned.

The projection SHALL expose only the fields in Section 33.

---

# 66. AE Artifact WA Source Projection

A narrow AE internal projection is authorized.

Recommended logical route:

```text
GET /internal/v1/wa-sources/artifacts/{artifact_id}/versions/{artifact_version_id}
```

Caller:

```text
nex-wa
```

The projection SHALL not return Artifact bytes.

---

# 67. WC WorkResult WA Supporting Projection

A narrow WC internal projection is authorized only for supporting lineage.

An exact-ID route MAY be provided:

```text
GET /internal/v1/wa-sources/work-results/{result_id}
```

For the Foundation AgentResult flow, WC SHALL also provide an exact,
tenant-scoped lookup by authoritative execution lineage, conceptually:

```text
GET /internal/v1/wa-sources/work-results/by-execution/{agent_execution_id}
```

with claim-generation / claimant / assignment verification as required by the
current WorkResult contract.

Caller:

```text
nex-wa
```

The projection SHALL not expose unbounded result payload.

## 67.1 WC Supporting-Evidence Discovery Contract

`WC_WORK_RESULT` is NOT a mandatory independent WA ingress in the initial
Foundation.

The canonical background-Agent path is:

```text
AE_AGENT_RESULT intake
        ↓
AgentResult source verification
        ↓
completion barrier verified
        ↓
WC WorkResult lookup by exact AgentExecution / Claim lineage
        ↓
matching WorkResult attached as SUPPORTING evidence
```

The WC WorkResult lookup SHALL fail closed when:

```text
tenant differs
source_execution_ref differs
claim_id / generation differs where required
assignment differs where required
submitted_agent_id differs
result hash / identity is inconsistent
```

No new WC multi-subscriber event bus is required for this Foundation path.

A future independent WC→WA delivery path requires an explicit later contract
and SHALL NOT weaken or duplicate the lineage-based supporting-evidence rule.

---

# 68. OA Human Verification Contract

When a Human actor must be verified, WA SHALL call OA through an admitted
service contract.

WA SHALL verify:

```text
tenant
subject identity
active subject lifecycle
tenant membership
```

It SHALL not copy credentials.

---

# 69. EOS Project Verification Contract

When ProjectRef is present, WA SHALL verify through EOS:

```text
same tenant
Project exists
Project status
```

For Human Project attribution requiring membership, EOS SHALL additionally
verify effective Project membership.

---

# 70. Project Membership Time Semantics

Where Human Project attribution is claimed for an historical event:

```text
occurred_at
```

SHOULD be evaluated against:

```text
valid_from
valid_to
```

rather than only current membership state.

Exact historical membership API contract is SRS scope.

---

# 71. Human Evidence Without Project

A valid Human-owned Artifact MAY be admitted with:

```text
project_ref = null
```

when no authoritative Project relationship exists.

P9 SHALL prefer:

```text
UNALLOCATED / project-neutral evidence
```

over guessing.

---

# 72. Agent Evidence Without Project

For IA:

```text
project_ref = null
```

is normal unless a separate authoritative Project reference exists.

For CA/PA/EA, missing required source Project lineage is an admission error.

---

# 73. Data Classification Contract

WA classification SHALL be:

```text
same as source
or
more restrictive
```

Never less restrictive.

Initial supported projection may use:

```text
INTERNAL
CONFIDENTIAL
RESTRICTED
```

subject to existing Platform classification vocabulary.

---

# 74. Raw Content Prohibition

WA persistence SHALL NOT store:

```text
raw prompt
hidden reasoning
Artifact bytes
full rendered document
credential
token
password
individual compensation
```

as WorkEvidence payload.

WA stores:

```text
refs
hashes
bounded facts
provenance
```

---

# 75. Evidence Processing State vs Evidence Lifecycle

Two concepts remain separate:

```text
Job processing:
QUEUED/RUNNING/SUCCEEDED/FAILED/CANCELLED

Evidence lifecycle:
ACTIVE/SUPERSEDED/INVALIDATED
```

Do not merge them.

---

# 76. Intake API Contract

Initial internal intake operation is authorized:

```text
POST /internal/v1/evidence-intake
```

The API SHALL:

```text
authenticate source service
validate source type/ref/revision/hash
derive deterministic Job id/idempotency key
enqueue WA_EVIDENCE_INGEST
return 202-style admission result
```

It SHALL NOT fetch/normalize the full source synchronously.

---

# 77. Intake Caller Contract

Initial source notification caller may be:

```text
nex-ae-api
```

for:

```text
AE_AGENT_RESULT
AE_ARTIFACT
```

No general public/browser evidence registration endpoint is required for P9
Foundation.

---

# 78. Source Notification Is Non-Authoritative

The intake request means:

```text
"please inspect this exact source"
```

not:

```text
"trust this payload as evidence"
```

The worker re-fetches the owner projection and verifies identity/hash.

---

# 79. Source Notification Failure

If source notification to WA fails:

```text
source remains valid
WA projection may be retried/backfilled
```

Source creation SHALL NOT be rolled back solely because WA is unavailable.

---

# 80. Recovery / Backfill Contract

P9 SHALL provide a bounded source reconciliation/backfill mechanism by P9.6
or earlier protected acceptance.

It must support:

```text
tenant scope
source type
time/cursor bound
idempotent re-enqueue
no raw content transfer
```

This closes the gap where a source notification was missed.

---

# 81. Backfill Is Not a Scheduler

Backfill may be:

```text
operator-triggered
bounded startup reconciliation
explicit protected maintenance command
```

It SHALL NOT introduce a general WA scheduler.

---

# 82. Human Approval Contract

No Human Approval is required for:

```text
AE AgentResult evidence
AE Artifact evidence
WC supporting evidence
source retry/replay
WorkAsset assembly
```

as long as authoritative source verification passes.

---

# 83. Artifact Creator Re-Approval

The Artifact owner/creator SHALL NOT be asked to approve evidence merely
because WA is recording it.

Creator/owner identity is provenance.

---

# 84. Downstream Confirmation Boundary

Human/Policy confirmation becomes relevant only when WA-derived data is
promoted to a consequential business fact.

Examples:

```text
Golden C finalized Project effort
0.05 MM allocation
LaborCostBasis application
Management Accounting posting
Project P/L
```

This belongs downstream.

---

# 85. NSL Contract

P9 Foundation requires no:

```text
NSL source
NSO
NSP
Skill Pack
Controlled WRITE Skill
```

WA-specific NSL work is explicitly deferred.

---

# 86. WC Delegation Contract

P9 Foundation evidence registration SHALL NOT create:

```text
WC WorkItem
WC Claim
WC Delegation
```

for the purpose of merely recording existing evidence.

Delegation may be introduced later only when genuinely new analysis work must
be performed.

---

# 87. Remote Model Contract

P9 Foundation source admission does not require:

```text
generation provider
embedding provider
reranking provider
```

The core path is deterministic.

---

# 88. WorkFact Contract

A separate physical:

```text
wa_work_fact
```

table is NOT required for P9.2/P9.3.

Normalized bounded facts may initially live in WorkEvidence/WorkAsset
projections.

A separate WorkFact table requires demonstrated need.

---

# 89. Contribution Candidate Contract Timing

Physical candidate persistence is deferred until P9.5.

P9.2/P9.3 SHALL NOT pre-encode a scoring formula.

---

# 90. Contribution Candidate Output Envelope

If P9.5 is implemented, the minimum candidate envelope SHALL contain:

```text
tenant_id
candidate_id

actor_type
actor_ref
agent_type_snapshot?

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

calculated_at
candidate_hash
```

The method/formula remains versioned.

---

# 91. Candidate Is Not Authority

Every P9 contribution output remains:

```text
CANDIDATE
```

It SHALL NOT directly become:

```text
final MM
salary
labor cost
performance grade
bonus
```

---

# 92. HumanEffortCandidate Restriction

P9 SHALL NOT calculate authoritative Human effort from:

```text
Artifact ownership alone
Artifact count alone
document count alone
message count alone
```

A HumanEffortCandidate requires an explicitly admitted method and sufficient
evidence.

---

# 93. AgentEffortCandidate Restriction

Agent effort/contribution may use AgentExecution/AgentResult evidence.

It SHALL NOT be converted to monetary Agent cost in P9.

---

# 94. Double-Counting Invariant

One logical work lineage SHALL NOT be counted multiple times merely because it
appears as:

```text
AgentResult
WorkResult
Artifact
```

Source equivalence and WorkAsset↔Evidence binding SHALL preserve one logical
work unit.

---

# 95. Quantity vs Value Invariant

P9 SHALL preserve:

```text
work quantity
!=
business value
!=
quality
!=
cost
!=
performance rating
```

No universal productivity score is authorized.

---

# 96. Privacy Contract

Detailed Human WorkEvidence is privacy-sensitive.

P9 SHALL support separate authorization for:

```text
individual evidence detail
Project aggregate
audit/provenance
```

Exact OA scopes are SRS scope, but unrestricted read is prohibited.

---

# 97. Query Contract

Foundation SHALL support bounded reads for at least:

```text
one WorkEvidence by exact ID
one WorkAsset by exact ID
WorkAssets by actor + bounded period
WorkAssets by Project + bounded period
evidence lineage for one WorkAsset
```

Pagination/order contracts belong to SRS.

---

# 98. Project Aggregate Query

P9 MAY provide Project aggregate work counts/summaries.

It SHALL not expose compensation or claim those counts are financial value.

---

# 99. Retention Contract

WA SHALL not copy Artifact bytes to preserve content after AE retention.

WA MAY retain approved:

```text
source identity
hash
provenance
classification
WorkAsset relationship
```

subject to a WA retention policy.

Exact retention duration is deferred to SRS/governance.

---

# 100. Source Deletion / Retention Interaction

If source content is later deleted:

```text
WA evidence identity/hash may remain
```

only if policy permits.

A missing source payload does not authorize reconstruction from WA.

---

# 101. Service Registry Changes

P9 implementation SHALL add `nex-wa` to every shared registry that requires a
known service ID, including at least:

```text
worker heartbeat
service logs where applicable
runtime endpoints
PostgreSQL target catalog
deployment artifact catalog
runtime/process topology
service-token audience/scope configuration
```

The implementation plan SHALL inventory exact files.

---

# 102. Runtime Endpoint

P9 SHALL define:

```text
NEX_WA_BASE_URL
```

Exact internal port SHALL be selected consistently with Platform topology in
SRS/implementation.

---

# 103. Contract Schema Deliverables

P9 SHALL add canonical schemas for at least:

```text
wa_evidence_intake_request
wa_evidence_intake_admission

wa_agent_result_source_projection
wa_artifact_source_projection
wa_wc_work_result_source_projection

wa_work_evidence
wa_work_asset
wa_work_asset_evidence_binding

wa_work_evidence_collection
wa_work_asset_collection

wa_error
```

Candidate schemas are added later with P9.5.

---

# 104. Negative Contract Fixtures

At minimum:

```text
unsupported source_type
source hash mismatch
same source identity with different hash
cross-tenant source
inactive/unknown Human subject
invalid Agent type
CA/PA/EA without Project lineage
IA free-text Project spoof
Artifact not READY
Artifact version mismatch
WC WorkResult execution lineage mismatch
duplicate AgentResult/WorkResult double-count attempt
raw content in intake Job payload
unapproved service caller
```

---

# 105. API Authorization Direction

Initial internal WA intake SHALL accept only admitted service identities.

At minimum:

```text
nex-ae-api
```

is an initial producer.

WA source verification calls SHALL use signed service tokens with exact target
audience and bounded scopes.

Exact scope strings are SRS/implementation contract values.

---

# 106. P9.2 Entry Contract

P9.2 may begin when the following are implemented/closed:

```text
nex-wa service skeleton
WA PostgreSQL
service_jobs
worker heartbeat
WA_EVIDENCE_INGEST
nex-wa-evidence-consumer
WorkEvidence
WorkAsset
binding table
basic exact-ID reads
```

No contribution formula is required.

---

# 107. P9.3 Entry Contract

P9.3 closes source intake:

```text
AE AgentResult projection
AE Artifact projection
WC supporting projection
intake API
source verification
source equivalence
queue/evidence idempotency
stale RUNNING recovery
retry/dead-letter/replay
```

---

# 108. P9.4 Entry Contract

P9.4 closes identity/scope:

```text
HUMAN/AGENT normalization
IA/CA/PA/EA snapshot
OA Human verification
EOS Project verification
EOS effective Project membership where required
privacy-safe reads
```

---

# 109. P9.5 Entry Contract

P9.5 MAY introduce contribution candidates only after P9.3/P9.4 prove:

```text
lineage
deduplication
source equivalence
Project attribution
privacy
```

No candidate method is allowed to bypass those foundations.

---

# 110. P9.6 Contract

P9.6 closes operational maturity:

```text
bounded backfill/reconciliation
operator job controls
dead-letter visibility
retention
query pagination
privacy projections
worker scaling/backpressure
stale Job recovery evidence
```

---

# 111. P9.7 Protected E2E

P9 final protected acceptance SHALL prove:

```text
1. AE Human-owned READY Artifact exists.
2. AE CA/PA/EA AgentResult exists with Project/claim lineage.
3. AgentResult before required ResultDelivery ACK is NOT admitted as positive post-work evidence.
4. The same AgentResult after authoritative delivery ACK is admitted.
5. Related WC WorkResult is discovered by exact AgentExecution/Claim lineage.
6. WC WorkResult attaches as supporting Agent evidence, not independent work.
7. Multiple source intake requests arrive concurrently.
8. WA service_jobs deduplicates exact source identities.
9. Multiple consumers can claim without duplicate execution.
10. Worker verifies source through owner APIs.
11. Human Artifact becomes ownership/deliverable evidence.
12. AgentResult becomes execution evidence only after completion barrier.
13. One logical Agent work is not double-counted.
14. No Human Approval is requested.
15. No WC Delegation is created.
16. No NSL is executed.
17. Worker crash/restart recovers stale RUNNING work through fenced/CAS ownership.
18. A stale pre-recovery worker cannot settle the recovered Job.
19. Evidence-level idempotency prevents duplicate WorkEvidence.
20. Source hash conflict fails closed.
21. Cross-tenant source fails closed.
22. PostgreSQL migrations/current-state pass.
23. Repository Full Gate passes.
24. Zero-residue acceptance passes.
```

---

# 112. Golden C Handoff Contract

P9 SHALL later provide evidence/candidate data without financial authority.

Expected future handoff:

```text
HumanEvidence / HumanEffortCandidate
        │
        ├─ actor_ref
        ├─ project_ref
        ├─ period
        ├─ evidence_set_hash
        ├─ method/version
        ├─ candidate value
        ├─ confidence
        └─ completeness
        │
        ▼
Golden C
        │
        ├─ Human/Policy confirmation
        ├─ 0.05-MM finalization
        ├─ Compensation/LaborCostBasis
        ├─ Project Labor Cost
        └─ Project P/L
```

WA SHALL NOT directly set compensation or final MM.

---

# 113. Golden C Manual Fallback

Even after P9:

```text
MANUAL
IMPORT
MANAGER_CONFIRMED
```

may remain Golden C fallback sources.

P9 evidence quality SHALL NOT be assumed perfect on day one.

---

# 114. Zero Job Handover Contract

WA contributes to Zero Job Handover by preserving:

```text
who/what produced work
which authoritative source proves it
which Project it belongs to when known
which Artifact/evidence supports it
which Agent/Human identity is linked
```

It does not replace PA/WC/AE histories.

---

# 115. Foundation Stop Conditions

Implementation SHALL return to architecture review if it starts introducing:

```text
scheduler
resource optimization
employee ranking
universal productivity score
salary
payroll
financial posting
Project P/L
Agent monetary cost
direct cross-service DB read
mandatory Human Approval for ordinary evidence
mandatory WC Delegation for ordinary evidence
NSL dependency for Foundation
external message broker without measured need
```

---

# 116. Closed Decisions

```text
P9-CC-01
NeX-WA is a new first-class service: nex-wa.

P9-CC-02
Initial processes are nex-wa-api and nex-wa-evidence-consumer.

P9-CC-03
WA owns its own PostgreSQL database.

P9-CC-04
WA reuses shared service_jobs, not ae_runtime_job.

P9-CC-05
Initial Job type is WA_EVIDENCE_INGEST.

P9-CC-06
JobQueue uses reference/hash payloads only.

P9-CC-07
Queue idempotency and evidence idempotency are separate required controls.

P9-CC-08
WA adds bounded stale-RUNNING recovery because the generic queue has no AE-like
lease-expiry ledger.

P9-CC-09
Authoritative evidence admission requires no Human Approval.

P9-CC-10
Artifact creator/owner re-approval is not required.

P9-CC-11
NSL is not required for P9 Foundation.

P9-CC-12
WC Delegation is not required for evidence registration.

P9-CC-13
Initial primary sources are AE_AGENT_RESULT and AE_ARTIFACT.

P9-CC-14
WC_WORK_RESULT is supporting Agent evidence only in Foundation.

P9-CC-15
WC WorkResult is not treated as a Human work source.

P9-CC-16
Agent actor identity is AGENT + agent_type snapshot IA/CA/PA/EA.

P9-CC-17
Human identity is OA subject_id.

P9-CC-18
Artifact ownership is not sufficient proof of Human effort.

P9-CC-19
IA Project attribution is never inferred from free text.

P9-CC-20
CA/PA/EA AgentResult Project/claim lineage is authoritative input.

P9-CC-21
One AgentExecution produces at most one semantic Agent WorkAsset.

P9-CC-22
AgentResult, WC WorkResult and Artifact can be multiple evidence facts for one
WorkAsset and SHALL NOT be double-counted.

P9-CC-23
WorkEvidence is immutable and correction uses supersession/invalidation.

P9-CC-24
WorkAsset and WorkEvidence remain distinct first-class concepts.

P9-CC-25
A WorkAsset↔Evidence binding relation is required.

P9-CC-26
WorkFact table is deferred unless later justified.

P9-CC-27
Contribution candidate persistence/formula is deferred until P9.5.

P9-CC-28
WA intake failure never retroactively invalidates source work.

P9-CC-29
No external message broker is required for Foundation.

P9-CC-30
Golden C remains the authority for final MM, cost, accounting and P/L.

P9-CC-31
Positive AE_AGENT_RESULT admission requires the authoritative result-publication
completion barrier: AgentResult SUCCEEDED/PARTIAL, AgentExecution SUCCEEDED, and
the required WORKSPACE_RESULT or WC_WORK_RESULT delivery ACKNOWLEDGED. Persisted
AgentResult status alone is not sufficient post-work evidence.

P9-CC-32
Stale RUNNING Job recovery SHALL use fenced/compare-and-set ownership semantics.
A successful recovery invalidates the prior worker's settlement authority; a
stale worker may not later complete/fail/retry the recovered Job using its old
claim.

P9-CC-33
WC_WORK_RESULT is not a mandatory independent WA ingress for initial Foundation.
For background Agent work it is resolved through exact AgentExecution/Claim
lineage during AE_AGENT_RESULT processing and attached as SUPPORTING evidence.

P9-CC-34
P9 SRS and Slice planning may proceed, but P9.2 production domain coding is
blocked until the Frozen Work Asset design/contracts are materialized,
reconciled against the current P8/P9 baseline, and any material contradiction
is either closed or handled through P9 Controlled Amendment.
```

---

# 117. Open Items Carried to SRS

The following are implementation-detail contracts, not architecture ambiguity:

```text
SRS-Q01
Exact SQL column types/lengths/index names.

SRS-Q02
Exact internal HTTP port for nex-wa.

SRS-Q03
Exact OA/EOS service-token scope strings.

SRS-Q04
Exact historical membership verification route.

SRS-Q05
Exact WorkAsset enum spelling.

SRS-Q06
Exact stale RUNNING timeout and concrete fencing token/CAS representation.

SRS-Q07
Exact pagination limits.

SRS-Q08
Exact retention duration.

SRS-Q09
Exact classification vocabulary mapping.

SRS-Q10
Exact P9.5 contribution method.
```

These MAY be decided in SRS without reopening this Contract Closure, provided
they preserve the semantics above.

---

# 118. Controlled Amendment Triggers

A new P9 Controlled Amendment is required before changing any of:

```text
WA becomes scheduler
WA owns Human identity
WA owns Project identity
WA directly reads another service DB
ordinary evidence requires Human Approval
ordinary evidence requires WC Delegation
Foundation requires NSL
AE RuntimeJob replaces WA service_jobs
AgentResult/WorkResult are counted as separate contribution units
positive AgentResult is admitted before its required delivery ACK/completion barrier
WC WorkResult becomes an independent mandatory Foundation ingress without new closure
stale RUNNING recovery removes fenced/CAS ownership safety
Artifact ownership becomes automatic Human MM
WA begins monetary cost calculation
WA begins Project P/L
```

---

# 119. Implementation Entry Decision

The architecture is sufficiently closed for:

```text
P9 SRS
P9 Implementation Slice Plan
P9.2 Foundation implementation preparation
```

However:

```text
P9.2 production domain coding
= NOT AUTHORIZED
until Section 4.1 Frozen WA reconciliation gate passes.
```

After that gate passes, P9.2 implementation may begin without reopening this
Closure unless the reconciliation identifies a material contradiction.

The first implementation work SHALL preserve the explicit small-scope boundary.

---

# 120. Final Contract

The P9 NeX-WA Foundation contract is:

```text
Authoritative source owner
        ↓
completed/admissible source state
        ↓
exact safe source reference
        ↓
nex-wa-api
        ↓
WA_EVIDENCE_INGEST
        ↓
service_jobs
        ↓
nex-wa-evidence-consumer
        ↓
deterministic source verification
        ↓
immutable WorkEvidence
        ↓
one bounded WorkAsset
        ↓
optional supporting evidence
```

with:

```text
NO Human Approval for ordinary evidence
NO WC Delegation for ordinary evidence
NO NSL requirement
NO scheduler
NO external broker
NO cross-service DB reads
NO salary/payroll
NO final MM
NO Project P/L
```

The final architectural position is:

> **NeX-WA Foundation is a small, owner-local, asynchronous post-work evidence
> service. It records what authoritative source systems can prove about
> Human-owned deliverables and completed Agent-executed work, preserves
> provenance, completion barriers and source equivalence, and creates immutable
> WorkEvidence/WorkAsset lineage without turning evidence collection into a
> workflow or approval process.**
