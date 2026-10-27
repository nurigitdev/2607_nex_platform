# P9 — NeX-WA (Work Asset)
# Pre-Architecture Decision v1.2

**Status:** PROPOSED PRE-ARCHITECTURE BASELINE v1.2 / PRE-SOURCE-AUDIT
**Phase:** P9 — NeX-WA / Work Asset Foundation
**Platform:** NeX Platform v2.1
**Primary New Domain:** NeX-WA — Work Asset / Work Evidence / Contribution Candidate
**Predecessor:** `P8_Final_AsBuilt_Baseline_and_P9_Handoff_v1.2.md`
**P8 Repository Branch:** `transition/p4-agent-runtime-foundation`
**P8-DEMO Merge HEAD:** `c3a1ea907387b67fe7a63407e4d668d13b1be8e7`
**P8-DEMO Merge Tree:** `7df03a1ff280baefbda4e56b1ff0e0818ef0bde3`
**P8 Status:** CLOSED / P9 ENTRY AUTHORIZED
**Next:** P9 NeX-WA Source Audit
**Revision Note:** v1.2 freezes approval-free background evidence admission, deterministic admission controls, and the minimal WA runtime architecture.
**Date:** 2026-10-27

---

# 1. Purpose

P9 establishes the minimum NeX-WA foundation required to convert work
execution evidence already produced by NeX Platform into durable,
queryable and quantitatively useful Work Assets.

The P9 objective is deliberately narrow.

P9 SHALL answer:

```text
Who or what performed work?
For which Project or business scope?
What authoritative source says that work occurred?
What evidence / artifact was produced?
When did it occur?
What bounded quantitative facts can be derived from that evidence?
What Human / Agent contribution candidate can be produced?
```

P9 SHALL NOT answer:

```text
What salary should be paid?
What is the employee's Project labor cost?
What accounting Voucher should be posted?
What is the final Project P/L?
Who should be assigned tomorrow?
Who is a better employee?
```

Those belong to other domains or later phases.

---

# 2. Executive Architecture Decision

P9 SHALL implement NeX-WA as a **Work Evidence and Work Asset Foundation**.

Canonical direction:

```text
Existing P8 Authoritative Sources
────────────────────────────────────────
OA Principal / Subject
AE Agent / AgentExecution / AgentResult
WC WorkItem / Claim / Assignment / WorkResult
EOS Project / ProjectMember
AE Artifacts / Evidence
        │
        │ references / admitted events
        ▼
NeX-WA
────────────────────────────────────────
WorkAsset
WorkEvidence
ActorRef
ProjectRef
SourceRef
Artifact/EvidenceRef
Quantitative Work Facts
Provenance / Hash / Classification
        │
        ▼
Bounded Aggregation
        │
        ├─ HumanEffortCandidate
        ├─ AgentEffortCandidate
        └─ ProjectContributionCandidate
```

The central principle is:

> **NeX-WA records and derives evidence-backed work facts. It does not become
> a scheduler, payroll engine, accounting system, authorization system, or
> model-owned performance evaluator.**

---

# 3. P8 Handoff Authority

P9 inherits all P8 v1.0, v1.1 and v1.2 invariants.

In particular P9 SHALL preserve:

```text
tenant isolation
OA identity and current authorization
AE AgentExecution authority
WC work coordination ownership
EOS Project / ProjectMember ownership
NSL deterministic execution ownership
approval-domain separation
BusinessOperation / idempotency boundaries
exactly-once controlled WRITE semantics where applicable
UNKNOWN_COMMIT_STATE semantics where applicable
verification semantics
attachment/evidence lineage
canonical three-segment operation naming
model output as candidate, never business authority
```

P9 SHALL NOT mutate or reinterpret a P8 authority boundary for implementation
convenience.

---

# 4. P9 Is Not a Scheduler

P8 Final As-Built explicitly hands P9 off as:

```text
NeX-WA / Work Asset
```

and not as a scheduler.

Therefore P9 SHALL NOT implement:

```text
task scheduling
resource scheduling
employee calendar optimization
automatic work assignment
Project staffing optimization
shift planning
deadline orchestration
personal productivity scheduling
```

WC remains the work-coordination domain.

A later scheduler may consume WA evidence, but scheduling is not WA ownership.

---

# 5. P9 Foundation Scope

P9 Foundation includes:

```text
WorkAsset identity
WorkEvidence identity
Human / Agent actor reference
Project reference
source-system reference
artifact / evidence reference
work occurrence period
quantitative work fact
classification
provenance
integrity hash
source idempotency
append-only evidence lineage

bounded aggregation

Human effort candidate
Agent effort candidate
Project contribution candidate

read/query APIs
privacy filtering
source freshness / completeness indicators
```

---

# 6. P9 Explicit Non-Goals

## 6.1 HR / Payroll

```text
Employee PII master
annual salary
monthly salary
bonus
allowance
tax
insurance
severance
payroll calculation
payroll payment
```

Golden C / EOS or later HR domains own these.

## 6.2 Accounting

```text
LaborCostBasis
Project labor cost amount
Management Voucher
Management Ledger
Project P/L
financial statement
```

These remain Golden C / EOS responsibilities.

## 6.3 Performance Evaluation

```text
employee rank
performance grade
promotion recommendation
compensation recommendation
bonus decision
disciplinary decision
```

P9 evidence SHALL NOT automatically become HR evaluation authority.

## 6.4 Productivity Scoring

P9 SHALL NOT freeze one universal:

```text
Human productivity score
Agent productivity score
employee efficiency score
```

as authoritative business truth.

Quantitative work facts may exist, but their interpretation remains
purpose-specific and policy-governed.

## 6.5 Agent Cost

P9 MAY record Agent execution evidence such as:

```text
runtime duration
model usage ref
tool-call count
WorkItem contribution
Artifact contribution
```

but SHALL NOT convert those facts into authoritative monetary Agent cost in P9.

## 6.6 Golden C Final Labor Ratio

P9 produces:

```text
EffortCandidate / ContributionCandidate
```

not automatically finalized accounting MM.

Final Labor Ratio / MM admission remains Golden C or an explicitly governed
downstream policy.

---

# 7. Service Ownership

## 7.1 NeX-WA Owns

```text
WorkAsset
WorkEvidence
WorkEvidenceSourceBinding
WorkFact
WorkAggregation
HumanEffortCandidate
AgentEffortCandidate
ProjectContributionCandidate
WA evidence provenance
WA evidence integrity
WA source idempotency
WA query/read projection
```

## 7.2 NeX-OA Continues to Own

```text
Human Principal / Subject
employee-number identity resolution
tenant membership
authentication
roles
groups
current authorization
subject lifecycle
```

WA SHALL reference OA identity.

WA SHALL NOT copy credential authority.

## 7.3 NeX-AE Continues to Own

```text
Agent identity
AgentExecution
AgentPlan
ExecutablePlan
ExecutableStep
StepResult
AgentResult
Artifact ownership
Conversation / Workspace lineage
```

WA SHALL reference AE identities and results.

WA SHALL NOT own Agent execution state.

## 7.4 NeX-WC Continues to Own

```text
WorkItem
Assignment
Claim
Delegation
WorkResult
Approval WorkItem
work coordination state
```

WA SHALL treat WC WorkResult and related references as authoritative evidence
sources where admitted.

## 7.5 NeX-EOS Continues to Own

```text
NVTProject
Project
ProjectMember
Organization
Account
Voucher
business transaction state
future Management Accounting / Project P&L
```

WA SHALL reference Project identity and membership.

WA SHALL NOT become Project SoR.

## 7.6 Existing NSL Boundary Is Unchanged

NSL remains an existing P8 platform capability, but it is not part of the P9
NeX-WA Foundation implementation scope.

P9 Foundation SHALL neither extend NSL nor require new WA-specific NSL Skills.

---

# 8. Deployment Boundary

P9 SHOULD introduce a distinct NeX-WA service boundary.

The Foundation runtime SHOULD begin with only two WA-owned process types:

```text
nex-wa-api
nex-wa-evidence-consumer
```

The architecture preference is:

```text
one service owner
one owner-local PostgreSQL boundary
one durable service-local JobQueue
one bounded evidence-consumer process type
no cross-service DB read
no cross-database foreign key
```

Candidate database names:

```text
nex_wa_dev
nex_wa_test
```

The exact deployment/migration naming is Contract Closure scope.

P9 Foundation SHALL NOT introduce a separate scheduler, dispatcher platform,
message broker, or Agent Runtime execution model merely to process WA
evidence.

---

# 9. Reference-First Architecture

P9 SHALL NOT become a copy of every source record.

Preferred:

```text
WA WorkAsset
→ source_ref
→ source_hash/version
→ evidence_refs
→ bounded derived facts
```

Not preferred:

```text
copy all WorkItem columns
copy all AgentExecution columns
copy entire AgentResult JSON
copy every Artifact payload
```

The rule is:

> **Reference authoritative source; persist only the WA-owned evidence identity,
> normalized facts and provenance required for reproducibility.**

---

# 10. Existing P8 Evidence Sources

Current P8 source already provides candidate evidence inputs.

## 10.1 WC WorkResult

Current WorkResult includes concepts such as:

```text
work_item_id
revision_no
result_type
technical_outcome
business_outcome
artifact_refs
evidence_refs
business_object_refs
source_execution_ref
source_plan_ref
claim_ref
assignment_ref
submitted_by
submitted_at
```

This is a strong WA source candidate.

## 10.2 AE AgentResult

AE AgentResult provides:

```text
AgentExecution lineage
StepResult lineage
Artifact refs
Evidence refs
Business refs
Result hash
completion verification
```

This is a strong Agent Work evidence source.

## 10.3 AE Artifact

AE Artifact / generated artifact lineage can prove:

```text
document created
file generated
evidence produced
business output produced
```

WA SHOULD reference Artifact identity rather than duplicate artifact bytes.

## 10.4 EOS Project / ProjectMember

Current P8 source already owns:

```text
Project
ProjectMember
OWNER / MANAGER / MEMBER / VIEWER
membership lifecycle
```

WA SHALL use these references for Project attribution validation.

## 10.5 OA Human Identity

OA already resolves:

```text
employee_id
→ subject_id
→ subject status
→ tenant membership
```

WA Human actor references SHOULD resolve to OA subject identity.

---

# 11. Actor Model

P9 SHALL support both Human and Agent work from the beginning.

Canonical actor types:

```text
HUMAN
AGENT
```

Potential future extension requires explicit Contract Closure.

---

# 12. Human Actor Reference

Human actor authority:

```text
actor_type = HUMAN
actor_ref  = OA subject_id
```

Optional display fields may be projected from authorized OA data but SHALL NOT
become WA identity authority.

WA SHALL NOT create a second Human identity registry.

---

# 13. Agent Actor Reference

Agent actor authority:

```text
actor_type = AGENT
actor_ref  = AE agent_id
```

Relevant execution source may additionally bind:

```text
AgentExecutionId
ExecutableStepId
AgentResultId
```

Agent identity SHALL not be represented as a fake OA employee.

---

# 14. Mixed Human-Agent Work

P9 SHALL support work in which both Human and Agent contribute.

Example:

```text
Human
→ creates/request work

Agent
→ performs analysis

Human
→ reviews

Agent
→ generates artifact

Human
→ accepts result
```

WA SHOULD preserve separate contribution evidence rather than collapse both
actors into one owner.

---

# 15. WorkAsset Concept

A `WorkAsset` is a durable WA-owned representation of a business-relevant work
outcome or work unit supported by authoritative evidence.

Logical concept:

```text
WorkAsset
────────────────────────────────
tenant_id
work_asset_id

asset_type
actor_type
actor_ref

project_ref
work_scope_ref

source_type
source_ref
source_version/hash

artifact_refs[]
evidence_refs[]
business_object_refs[]

occurred_at
period_key

classification
status

provenance_hash
asset_hash

created_at
version
```

Exact physical schema is deferred.

---

# 16. WorkEvidence Concept

`WorkEvidence` captures one immutable evidence fact supporting a WorkAsset or
ContributionCandidate.

Logical concept:

```text
WorkEvidence
────────────────────────────────
tenant_id
work_evidence_id

source_type
source_ref
source_event_id
source_hash

actor_type
actor_ref

project_ref

evidence_type
metric_type
metric_value
unit

occurred_at
observed_at

classification
evidence_hash
```

---

# 17. WorkAsset vs WorkEvidence

The two concepts SHOULD remain distinct.

```text
WorkEvidence
= atomic evidence fact

WorkAsset
= business-relevant normalized work object / aggregation anchor
```

Example:

```text
WorkEvidence:
  WorkResult submitted
  Artifact created
  Review accepted

        ↓

WorkAsset:
  "Project A monthly design deliverable"
```

P9 Source Audit SHALL confirm whether both physical aggregates are needed in
v1 or whether one can initially be a projection.

---

# 18. Evidence Source Types

Initial candidate source types:

```text
WC_WORK_ITEM
WC_WORK_RESULT

AE_AGENT_EXECUTION
AE_STEP_RESULT
AE_AGENT_RESULT
AE_ARTIFACT

EOS_PROJECT_OPERATION
EOS_BUSINESS_OBJECT_REF

MANUAL_EVIDENCE
IMPORT_EVIDENCE
```

Only source types justified by actual source contracts should be admitted.

---

# 19. Evidence Source Admission

A source is not trusted merely because a caller says it exists.

WA SHALL validate source identity through an owner API, signed event, durable
outbox event, or other admitted source contract.

Conceptually:

```text
source candidate
        ↓
source owner verification
        ↓
exact tenant / identity / version/hash
        ↓
WA evidence admission
```

---

# 20. No Direct Cross-Service Database Reads

P9 SHALL NOT:

```text
SELECT directly from AE DB
SELECT directly from WC DB
SELECT directly from EOS DB
SELECT directly from OA DB
```

to build WA state.

Source interaction SHALL use:

```text
owner API
admitted event
outbox delivery
immutable reference
```

This preserves service ownership and future evolvability.

---

# 21. WA JobQueue Foundation

P9 SHALL use the existing NeX Platform shared service-local JobQueue pattern
for concurrent and restart-safe evidence intake.

The architectural decision is:

```text
shared service JobQueue pattern
= general service background work

AE RuntimeJob
= AgentExecution / ExecutableStep progression
```

NeX-WA SHALL use the former and SHALL NOT reuse `ae_runtime_job` as its
evidence-ingestion queue.

Conceptual WA runtime:

```text
AE / WC / EOS / Manual Source
        │
        ▼
nex-wa-api
  Source Admission
  Request Validation
  Idempotency Key
        │
        ▼
WA service_jobs
  QUEUED
  RUNNING
  SUCCEEDED
  FAILED
  CANCELLED
        │
        ▼
nex-wa-evidence-consumer
  Source Verification
  Actor Resolution
  Project Resolution
  Evidence Normalization
        │
        ▼
WorkEvidence / WorkAsset / WorkFact
```

Initial Foundation SHOULD use one Job type:

```text
WA_EVIDENCE_INGEST
```

Additional Job types SHALL NOT be introduced until a demonstrated requirement
exists.

The queue payload SHOULD contain references and hashes rather than raw
business content.

Preferred payload shape:

```text
job_type
tenant_id
source_type
source_ref
source_event_id / source_revision
source_hash
actor_ref
project_ref
trace / correlation refs
```

Raw document content, raw prompts, credentials, and unrestricted business
payloads SHALL NOT be placed in the JobQueue.

---

# 22. JobQueue Idempotency and Replay

WA SHALL implement two independent idempotency boundaries.

## 22.1 Queue-level idempotency

The service JobQueue SHOULD deduplicate by:

```text
job_type + idempotency_key
```

The idempotency key SHOULD be derived from authoritative source identity, for
example:

```text
tenant_id
source_type
source_ref
source_revision / source_event_id
```

Repeated delivery of the same source fact SHALL resolve to the same semantic
Job.

## 22.2 Evidence-level idempotency

Queue deduplication alone is insufficient.

A worker may persist WorkEvidence and fail before the Job is marked
`SUCCEEDED`.

Therefore WorkEvidence SHALL independently enforce a unique semantic source
identity.

Required recovery behavior:

```text
WorkEvidence persisted
        ↓
worker/process crash
        ↓
same Job retried
        ↓
existing source evidence found
        ↓
existing evidence reused
        ↓
Job completed successfully
```

This guarantees that retries, worker restarts and source replay do not create
duplicate semantic evidence.

---

# 23. JobQueue Concurrency

P9 Foundation SHALL support concurrent evidence intake without introducing a
new scheduling domain.

Initial deployment may use one consumer:

```text
nex-wa-evidence-consumer-1
```

The same process type SHOULD be horizontally scalable later:

```text
nex-wa-evidence-consumer-1
nex-wa-evidence-consumer-2
nex-wa-evidence-consumer-3
```

Workers claim queued work through the service-local durable queue.

The API contract SHALL NOT change when worker count changes.

Worker coordination SHOULD reuse the Platform's proven patterns for:

```text
claim / lock ownership
bounded retry
heartbeat
graceful shutdown
restart recovery
```

Exact lease/claim mechanics are Source Audit / Contract Closure scope.

---

# 24. No New Message Broker in Foundation

P9 Foundation SHALL NOT introduce:

```text
Kafka
RabbitMQ
NATS
Redis Streams
```

solely for WA evidence ingestion.

The default Foundation implementation SHOULD use:

```text
PostgreSQL
+
service_jobs
+
WA evidence consumer
```

A separate broker may be reconsidered only after measured throughput,
availability or operational requirements prove that the service-local
PostgreSQL JobQueue is insufficient.

---

# 25. WA Reliability Boundary

WA evidence ingestion is an owner-local persistence problem and SHOULD remain
simpler than the P8 cross-service Controlled WRITE flow.

Foundation reliability requires:

```text
durable enqueue
source idempotency
evidence idempotency
bounded retry
restart safety
worker heartbeat
deterministic source verification
append-only evidence
```

P9 Foundation does NOT require the full P8 Voucher state machine such as:

```text
Human Approval
UNKNOWN_COMMIT_STATE
cross-service WRITE reconciliation
post-WRITE financial verification
```

unless a later WA operation explicitly creates such a business requirement.

---

# 26. Background Evidence Admission Without Human Approval

P9 Foundation SHALL treat registration of authoritative work evidence as a
natural background processing activity.

The core rule is:

```text
Evidence Admission
!=
Business Approval
```

When an authoritative source already proves that an activity or artifact
occurred, NeX-WA SHALL NOT require the artifact creator, Project manager,
approver, or another Human to approve the evidence merely so that WA can
record it.

Canonical flow:

```text
Authoritative Source
AE / WC / EOS
        │
        │ source event / admitted reference
        ▼
nex-wa-api
  deterministic source admission
        │
        ▼
WA service_jobs
  WA_EVIDENCE_INGEST
        │
        ▼
nex-wa-evidence-consumer
  source verification
  tenant verification
  actor verification
  Project verification
  hash/version verification
  idempotency verification
  evidence normalization
        │
        ▼
WorkEvidence
        │
        ▼
WorkAsset / WorkFact
```

No ordinary Foundation path above contains:

```text
creator re-approval
manager approval
WC Approval WorkItem
Human Gate
NSL approval
```

The absence of Human Approval SHALL NOT weaken control.

The required distinction is:

```text
Human Approval
= NOT REQUIRED for authoritative evidence admission

Deterministic Admission
= REQUIRED
```

Before a source fact is admitted, WA SHALL verify at least the applicable
subset of:

```text
source exists and is admissible
tenant matches
source identity/version/hash matches
actor identity is authoritative
Project identity/scope is authoritative
classification is admissible
source is not a conflicting duplicate
idempotency identity is valid
```

If those checks fail, WA SHALL reject, retry, or quarantine the intake
according to the later Contract Closure semantics. It SHALL NOT ask a Human to
approve invalid or unverifiable evidence as a substitute for source authority.

## 26.1 Artifact Creator Approval

The artifact creator SHALL NOT be required to re-confirm or re-approve an
authoritative system-generated evidence record.

Examples:

```text
AE AgentResult proves Agent-produced Artifact
WC WorkResult proves submitted work result
AE Artifact lineage proves generated deliverable
EOS event proves business-object operation
```

For such sources, creator identity is provenance, not an approval gate.

## 26.2 Evidence Processing State

WA evidence processing state SHOULD describe technical/admission progress, not
business approval.

Candidate processing states may include:

```text
QUEUED
RUNNING
ADMITTED
FAILED
CONFLICT
RETRY_PENDING
```

or an equivalent bounded vocabulary.

Foundation SHOULD NOT model ordinary system-generated evidence as:

```text
PENDING_APPROVAL
APPROVED
REJECTED
```

because that would incorrectly transform evidence collection into a business
approval workflow.

## 26.3 Candidate Calculation and Approval Boundary

A contribution or effort candidate MAY also be calculated automatically from
admitted evidence.

Preferred separation:

```text
Authoritative Evidence
        │
        │ background / automatic
        ▼
WorkEvidence
        │
        │ deterministic / automatic
        ▼
ContributionCandidate / HumanEffortCandidate
        │
        │ still a candidate
        ▼
Downstream Business Authority
```

Human or policy approval MAY become appropriate only when a candidate is
promoted into a consequential downstream business fact, for example:

```text
Golden C finalized Project effort
0.05-MM accounting allocation
LaborCostBasis
Management Accounting
Project P/L
```

That approval belongs to the downstream business boundary, not to WA evidence
registration.

## 26.4 Manual Evidence

Manual/import evidence remains explicitly distinguishable from authoritative
system-generated evidence.

It MAY be registered without forcing an immediate third-party approval, but it
SHALL retain provenance such as:

```text
source_type = MANUAL_EVIDENCE / IMPORT_EVIDENCE
submitted_by
source_ref
classification
observed_at
```

Downstream consumers MAY require stronger confirmation before such evidence is
used for financial or other consequential authority.

---

# 27. Evidence Intake Modes

P9 Foundation SHOULD support two intake classes.

## 27.1 Event / Source-Driven Intake

Preferred.

```text
WC / AE / EOS source event
→ WA intake
→ idempotent evidence admission
```

## 27.2 Controlled Manual / Import Evidence

Allowed for gaps and early adoption.

```text
authorized manual/import
→ explicit provenance
→ classification
→ bounded validation
→ WA evidence
```

Manual evidence SHALL never masquerade as system-generated evidence.

---

# 28. Source Idempotency

Same source event/fact SHALL produce at most one semantic WA evidence record.

Canonical identity SHOULD bind some form of:

```text
tenant
source_type
source_ref
source_event_id or source_revision
evidence_type
```

Exact key is Contract Closure scope.

---

# 29. Append-Only Evidence Principle

Admitted WorkEvidence SHOULD be append-only.

If authoritative source correction occurs:

```text
old evidence remains
+
new correction/supersession evidence
```

rather than silent overwrite.

This preserves:

```text
auditability
historical reproducibility
candidate recalculation lineage
```

---

# 30. WorkAsset Lifecycle

Initial conceptual states:

```text
ACTIVE
SUPERSEDED
INVALIDATED
```

or equivalent.

Physical lifecycle is deferred to Contract Closure.

Hard delete SHOULD NOT be the ordinary correction mechanism once evidence has
been used by a downstream candidate.

---

# 31. Project Attribution

A WorkAsset MAY be Project-scoped.

When `project_ref` exists, WA SHALL verify:

```text
same tenant
Project exists
Project identity authoritative
Project relationship valid for evidence semantics
```

WA SHALL not infer Project identity from free text alone.

---

# 32. Human Project Attribution

Human Project contribution evidence SHOULD be compatible with:

```text
EOS ProjectMember
```

For strong Project attribution:

```text
Human actor
+
ProjectRef
+
effective Project membership
```

SHOULD normally be present.

Exceptions require explicit policy/evidence.

---

# 33. Agent Project Attribution

Agent contribution may bind Project through trusted lineage such as:

```text
AgentExecution.project_id
WorkItem.project_ref
source business object
```

Agent Project association SHALL not be invented from LLM text.

---

# 34. Quantitative Work Facts

P9 SHOULD support bounded quantitative facts without declaring one universal
productivity score.

Candidate metrics may include:

```text
WORK_ITEM_COMPLETED_COUNT
WORK_RESULT_ACCEPTED_COUNT
ARTIFACT_CREATED_COUNT
REVIEW_COMPLETED_COUNT

ACTIVE_WORK_DURATION
ELAPSED_DURATION

AGENT_EXECUTION_COUNT
AGENT_STEP_COUNT
TOOL_INVOCATION_COUNT

DOCUMENT_COUNT
EVIDENCE_COUNT
```

Exact metric catalog SHALL be Source Audit / Contract Closure driven.

---

# 35. Metric Semantics Must Be Explicit

A metric is meaningless without semantics.

Every admitted metric SHOULD define:

```text
metric_code
meaning
unit
source_type
aggregation rule
time semantics
classification
known limitations
```

P9 SHALL NOT compare unrelated metrics as though they were equivalent work.

---

# 36. Quantity Is Not Value

P9 SHALL preserve:

```text
quantity
!= quality
!= value
!= cost
!= employee performance
```

For example:

```text
10 WorkItems
```

does not automatically mean more contribution than:

```text
2 highly complex WorkItems
```

P9 should expose evidence, not make unsupported management judgments.

---

# 37. Contribution Candidate

P9 MAY derive a bounded `ProjectContributionCandidate`.

Conceptually:

```text
ProjectContributionCandidate
────────────────────────────────
tenant_id
candidate_id

actor_type
actor_ref
project_ref
period_key

evidence_set_ref/hash

contribution_value
contribution_unit
method_ref
method_version

confidence
completeness

status
calculated_at
candidate_hash
```

This is a candidate, not accounting authority.

---

# 38. HumanEffortCandidate

P9 MAY derive:

```text
HumanEffortCandidate
```

from evidence-backed Project contribution.

Example:

```text
Employee A / 2026-11

Project A candidate = 0.65
Project B candidate = 0.25
Internal candidate  = 0.10
```

P9 SHALL NOT automatically classify this as final payroll/accounting MM.

---

# 39. AgentEffortCandidate

P9 MAY derive:

```text
AgentEffortCandidate
```

using AgentExecution / WorkResult / Artifact evidence.

It may represent:

```text
relative contribution
work quantity
execution effort indicator
```

It SHALL NOT automatically become Agent monetary cost.

---

# 40. Candidate Confidence

Derived candidates SHOULD expose:

```text
confidence
completeness
evidence_count
evidence freshness
method version
```

A low-confidence candidate SHALL not silently become authoritative.

---

# 41. Candidate Method Versioning

Every derived candidate SHALL bind an exact method.

Example:

```text
method_ref = WA.PROJECT_CONTRIBUTION.METHOD
method_version = 1.0.0
```

A changed method SHALL produce a new candidate revision/hash.

Historical candidates remain reproducible.

---

# 42. Deterministic vs Model-Assisted Analysis

Initial P9 SHOULD prefer deterministic aggregation where possible.

LLM MAY assist with:

```text
evidence classification candidate
semantic grouping candidate
work summary
artifact type candidate
```

but SHALL NOT authoritatively decide:

```text
tenant
actor identity
ProjectRef
source validity
final contribution ratio
final MM
cost
performance rating
```

---

# 43. Model Output Is Candidate Only

Canonical rule:

```text
LLM / model output
        ↓
candidate
        ↓
schema validation
        ↓
authoritative source checks
        ↓
deterministic admission
```

P9 SHALL reuse the P5/P6.5/P8 candidate-authority philosophy.

---

# 44. Golden C Handoff Boundary

P9 should provide Golden C with evidence-backed upstream inputs.

Preferred future flow:

```text
NeX-WA Evidence
        ↓
HumanEffortCandidate
        ↓
Manager / policy confirmation
        ↓
Golden C ProjectEffortAllocation
        ↓
EOS Compensation / LaborCostBasis
        ↓
Project Labor Cost
        ↓
Management Ledger
        ↓
Project P/L
```

P9 stops before monetary cost.

---

# 45. Manual Fallback After P9

Even after P9, Golden C SHOULD retain controlled fallback:

```text
WA_EVIDENCE_DERIVED
MANAGER_CONFIRMED
MANUAL
IMPORT
```

The presence of WA does not require perfect automated evidence coverage from
day one.

---

# 46. Human Confirmation

Initial production direction SHOULD allow:

```text
WA Candidate
        ↓
Human / Manager review
        ↓
confirmed downstream allocation
```

rather than immediate autonomous financial use.

This gives WA algorithms room to mature without weakening accounting control.

---

# 47. Evidence Completeness

WA SHOULD distinguish:

```text
NO_EVIDENCE
PARTIAL
SUFFICIENT
COMPLETE
```

or an equivalent explicit status.

Absence of evidence SHALL NOT mean:

```text
zero work
```

unless a policy explicitly proves that equivalence.

---

# 48. Evidence Freshness

Candidate calculations SHOULD bind:

```text
evidence_as_of
source_freshness
period closure status
```

A stale candidate SHALL be distinguishable from a current candidate.

---

# 49. Privacy

Work evidence may itself reveal sensitive behavior.

P9 SHALL classify and protect:

```text
employee work activity
Project participation
documents / artifacts
Agent interaction
work timing
business object references
```

WA SHALL not become an unrestricted employee surveillance database.

---

# 50. Purpose Limitation

Access to detailed WA evidence SHOULD be purpose-scoped.

Potential purposes:

```text
PROJECT_CONTINUITY
WORK_HISTORY
CONTRIBUTION_REVIEW
GOLDEN_C_ALLOCATION
AUDIT
```

A future privacy policy may restrict raw evidence while allowing aggregate
contribution candidates.

---

# 51. Human Detail vs Aggregate

P9 SHOULD separate:

```text
individual detailed work evidence
```

from:

```text
Project-level aggregate contribution
```

similar to Golden C's planned restricted-detail/aggregate boundary.

Exact privacy thresholds are deferred.

---

# 52. Agent Privacy / Security

Agent evidence may contain:

```text
prompt-derived context
business refs
artifact refs
tool interactions
```

WA SHOULD store protected refs and bounded facts.

Raw prompts / hidden reasoning / credentials SHALL NOT become WorkEvidence.

---

# 53. Data Classification

Initial candidate classification tiers:

```text
INTERNAL
CONFIDENTIAL
RESTRICTED
```

Source classification SHOULD be preserved or strengthened, never silently
weakened.

---

# 54. Provenance

Every WorkEvidence SHALL identify:

```text
source system
source identity
source revision/hash/event ID
observed time
admission method
actor
Project scope where applicable
```

Derived candidate SHALL identify exact evidence set/hash and method version.

---

# 55. Hashing

P9 SHALL use canonical semantic hashes for WA-owned records where appropriate.

A derived candidate hash SHOULD bind:

```text
actor
Project
period
ordered evidence identities/hashes
method version
candidate value
confidence/completeness
```

Raw secret/private payloads SHALL not be exposed through unsafe digest design.

---

# 56. Reliability Model

P9 Foundation reliability focuses on evidence ingestion rather than controlled
financial mutation.

Primary requirements:

```text
source idempotency
append-only evidence
duplicate suppression/reuse
restart safety
event replay safety
tenant isolation
source lineage integrity
deterministic aggregation
```

P9 SHALL reuse P8 infrastructure patterns where appropriate rather than
copying the full Voucher WRITE state machine unnecessarily.

---

# 57. Exactly-Once Evidence Semantics

For one canonical source fact:

```text
same source identity
+ same semantic payload
→ same WA evidence

same source identity
+ different semantic payload
→ conflict / correction path
```

A delivery retry SHALL not duplicate semantic evidence.

---

# 58. Unknown Source State

If WA cannot verify an authoritative source:

```text
dependency unavailable
source missing ambiguously
source hash mismatch
```

it SHALL NOT invent evidence.

The intake remains:

```text
PENDING / FAILED / RETRYABLE
```

according to later contract semantics.

---

# 59. Source Correction

When a source is authoritatively corrected:

```text
old evidence
→ SUPERSEDED / INVALIDATED

new evidence
→ new immutable evidence record
```

Downstream candidates referencing old evidence SHALL remain historically
traceable.

---

# 60. Work Evidence Queries

P9 SHOULD provide bounded queries such as:

```text
Work Assets by actor / period
Work Assets by Project / period
Evidence for one WorkAsset
Contribution candidate by actor / Project / period
Project contribution summary
Agent contribution summary
Human contribution summary
```

Exact API contracts are deferred.

---

# 61. No RAG as Work SoR

RAG/vector retrieval MAY help a user discover WA records.

It SHALL NOT establish:

```text
actor identity
Project membership
source validity
contribution authority
```

WA business facts come from structured authoritative evidence.

---

# 62. NeX-CX Relationship

CX MAY index display-safe WA summaries later.

Conceptually:

```text
WA authoritative structured fact
        ↓
safe projection
        ↓
CX retrieval
```

CX SHALL NOT become WA SoR.

---

# 63. NeX-AG Relationship

AG may later own or project:

```text
WA policy
evidence classification policy
retention
audit
candidate method certification
```

The exact governance split is P9 Source Audit scope.

---

# 64. NeX-MO Relationship

MO may support model-assisted evidence classification or summarization.

MO SHALL NOT own WA source data or final contribution authority.

Remote generation is not required for the earliest WA persistence slices.

---

# 65. NSL and Skill Pack Explicitly Deferred

P9 NeX-WA Foundation SHALL NOT require NSL Skill implementation.

Foundation evidence intake, WorkEvidence persistence, WorkAsset construction
and deterministic aggregation are service-owned WA responsibilities.

Therefore the following are explicitly deferred:

```text
WA-specific NSL READ Skills
WA-specific NSL WRITE Skills
Skill Pack packaging
Skill Pack entitlement
NSP distribution for WA operations
natural-language WA mutation
```

These may be reconsidered after the WA Foundation has stable source, evidence,
query and contribution contracts.

This decision intentionally keeps P9 focused on:

```text
Evidence Intake
JobQueue
WorkEvidence
WorkAsset
WorkFact
Contribution Candidate
```

and avoids coupling Foundation closure to NSL or Skill Pack work.

---

# 66. Persistence Direction

NeX-WA SHOULD own an independent PostgreSQL schema/database.

Candidate logical tables:

```text
wa_work_asset
wa_work_evidence
wa_evidence_source_binding
wa_work_fact
wa_contribution_candidate
wa_candidate_evidence_binding
```

This is a conceptual inventory only.

Source Audit may collapse or refine it.

---

# 67. P9 Must Not Pre-Design Golden C Tables

P9 SHALL NOT create:

```text
employee_compensation
payroll_snapshot
labor_cost_basis
management_voucher
project_pl
```

merely because Golden C will later consume WA output.

Domain boundaries remain separate.

---

# 68. Evidence Ingestion Architecture

Preferred future shape:

```text
AE / WC / EOS
 authoritative event/API
        │
        ▼
WA Source Adapter
        │
        ▼
Source Admission
        │
        ▼
Idempotent Evidence Persistence
        │
        ▼
WorkAsset / WorkFact
        │
        ▼
Aggregation
```

The source owner remains responsible for the source fact.

---

# 69. Synchronous vs Asynchronous Intake

Both MAY exist.

Preferred event-driven flow for durable production evidence:

```text
Source outbox/event
→ WA consumer
```

Query/backfill may use:

```text
owner API
→ deterministic backfill
```

Exact initial intake mechanism requires Source Audit.

---

# 70. Backfill

P9 SHOULD anticipate bounded backfill from existing P8 evidence.

Potential source history:

```text
WC WorkResult
AE AgentResult
AE Artifact
```

Backfill SHALL be:

```text
tenant-scoped
idempotent
bounded
restart-safe
source-version aware
```

P9 SHALL NOT require full historical backfill for Foundation acceptance.

---

# 71. Period Model

WA evidence requires time grouping but does not own payroll periods.

Initial WA period may be:

```text
occurred_at
calendar day/month projection
explicit query range
```

Golden C PayrollPeriod remains EOS/Golden C domain.

WA candidate may expose:

```text
period_start
period_end
```

without creating payroll authority.

---

# 72. Work Duration

P9 MAY represent duration only when the source semantics support it.

Examples:

```text
claim duration
execution duration
active task duration
```

P9 SHALL NOT infer actual human working time solely from:

```text
message timestamp difference
browser session duration
Agent response time
```

without explicit policy/evidence.

---

# 73. Contribution Candidate Is Not MM

P9 candidate unit SHOULD initially be independent of accounting MM where
possible.

Examples:

```text
normalized contribution ratio
weighted contribution points
evidence-backed share
```

Golden C may map an admitted candidate to:

```text
0.05-MM effort units
```

under its own policy.

This keeps WA evidence semantics independent from accounting granularity.

---

# 74. Candidate Normalization

If P9 produces a normalized Project contribution distribution:

```text
Σ candidate shares = 1.0
```

may be useful for one actor/period.

However this SHALL NOT be frozen until Source Audit confirms evidence quality
and handling of:

```text
INTERNAL
COMMON
UNALLOCATED
non-Project work
missing evidence
```

---

# 75. Incomplete Evidence

P9 SHALL explicitly support:

```text
unallocated / unknown contribution
```

rather than forcing every work fact into a Project.

This is important for Golden C fallback.

---

# 76. Human vs Agent Method Separation

Human and Agent evidence may use different derivation methods.

P9 SHALL NOT require:

```text
same metric weights
same duration semantics
same contribution algorithm
```

for HUMAN and AGENT.

They share the WorkAsset architecture, not necessarily the scoring model.

---

# 77. Method Certification

A contribution method SHOULD eventually be versioned/certified.

Candidate states:

```text
DRAFT
ACTIVE
DEPRECATED
REVOKED
```

A candidate must record the exact method version used.

Exact policy ownership is deferred.

---

# 78. Explainability

ContributionCandidate SHOULD be explainable through bounded evidence.

A user or auditor should be able to answer:

```text
Which evidence contributed?
Which method/version was used?
What was excluded?
Was the evidence complete?
```

P9 SHALL NOT require exposing private raw payloads to provide explanation.

---

# 79. Zero Job Handover Relationship

NeX-WA contributes to Zero Job Handover by preserving:

```text
work history
business artifact linkage
Project contribution evidence
Human/Agent execution lineage
```

It supplements, not replaces:

```text
PA Project history
Conversation journal
Artifacts
WorkItems
```

WA is a structured evidence layer over those sources.

---

# 80. P9 Foundation Demo

A minimal P9 demo SHOULD prove something like:

```text
1. Human is a Project member.
2. WC WorkItem is completed.
3. WorkResult carries Artifact/Evidence refs.
4. AE Agent also contributes an AgentResult/Artifact.
5. Multiple source events are admitted concurrently into WA `service_jobs`.
6. No creator/manager approval is requested for authoritative evidence intake.
7. `nex-wa-evidence-consumer` claims and processes queued intake jobs.
8. WA deterministically verifies source, tenant, actor, Project and hash/version.
9. WA ingests all source facts idempotently.
10. WA creates WorkEvidence / WorkAssets / WorkFacts.
11. Replaying the same source events creates zero duplicate evidence.
12. Worker restart resumes safely without duplicate evidence.
13. Source correction creates explicit supersession.
14. No scheduling, NSL, salary, cost or P/L is required.
```

---

# 81. P9 Foundation Acceptance

P9 Foundation should not be considered complete until it proves:

```text
Human evidence ingestion
Agent evidence ingestion
approval-free authoritative evidence admission
no artifact-creator re-approval
concurrent JobQueue admission
worker claim / retry / restart recovery
Project attribution
source identity verification
tenant / actor / Project / hash verification
queue-level idempotency
evidence-level idempotency
append-only/supersession
tenant isolation
privacy filtering
deterministic aggregate
candidate provenance
actual PostgreSQL
zero residue
```

---

# 82. Remote Provider Requirement

Remote generation SHOULD NOT be required for the first WA foundation slices.

P9 core acceptance SHOULD be deterministic.

A remote provider MAY be introduced later for:

```text
semantic evidence classification
work summary candidate
candidate explanation
natural-language WA query
```

but these are not WorkAsset authority.

---

# 83. Initial P9 Phase Proposal

Recommended P9 decomposition:

```text
P9.0  Pre-Architecture / Boundary
P9.1  Source Audit / Ownership / Contract Inventory
P9.2  WorkAsset / WorkEvidence Foundation
P9.3  Evidence Intake / Backfill
P9.4  Human / Agent Actor + Project Attribution
P9.5  Contribution / Effort Candidate
P9.6  Query / Privacy / Reliability
P9.7  Protected E2E / Full Gate / Final As-Built
```

The exact Slice count is intentionally not defined yet.

---

# 84. P9.0 Exit

This Pre-Architecture stage is complete when stakeholders accept:

```text
WA is not scheduler
WA is not accounting
WA is not payroll
WA is not performance ranking

WA owns work/evidence facts
WA supports HUMAN + AGENT
WA references P8 sources
WA does not copy source SoR
WA uses owner-local service JobQueue for concurrent evidence intake
WA does not use AE RuntimeJob for evidence ingestion
WA Foundation does not require NSL
WA produces candidates, not accounting authority
Golden C consumes WA after P9
```

---

# 85. P9.1 Source Audit Targets

P9 Source Audit SHALL inspect at least:

```text
WC WorkItem
WC Claim / Assignment
WC WorkResult
WC outbox/event delivery

AE AgentIdentity
AE AgentExecution
AE ExecutableStep
AE StepResult
AE AgentResult
AE Artifact / Evidence refs

EOS NVTProject
EOS Project
EOS ProjectMember

OA Subject / Employee ID resolution

P8 event/outbox contracts
P8 evidence classification
P8 retention/audit conventions

Frozen:
23_NeX_Work_Asset_Human_Effort_and_Labor_Allocation_Design_v2.0
and its reference contracts
```

The Frozen Work Asset design should be reconciled at Source Audit / Contract
Closure before P9 implementation is frozen.

---

# 86. P9 Source Audit Questions

The audit should answer:

```text
SA-Q01
Which P8 objects are authoritative WA sources?

SA-Q02
Which sources already publish durable events/outbox records?

SA-Q03
Which sources require API-based backfill?

SA-Q04
Do WorkAsset and WorkEvidence both require physical tables in v1?

SA-Q05
What is the minimum common HUMAN / AGENT actor contract?

SA-Q06
How is Project attribution proven for each source type?

SA-Q07
Which metrics are source facts vs derived facts?

SA-Q08
How are corrections/supersession represented?

SA-Q09
What privacy classes apply to detailed Human work evidence?

SA-Q10
What exact contribution candidate is useful to Golden C?

SA-Q11
Can candidate generation remain deterministic in P9 v1?

SA-Q12
What P9 data is safe to expose to PA / IA / executives?

SA-Q13
What retention policy applies?

SA-Q14
What source event replay/recovery semantics can be reused from P8?

SA-Q15
What Frozen Work Asset contracts constrain the implementation?

SA-Q16
Which existing shared JobQueue adapter/runtime primitives can WA reuse directly?

SA-Q17
What claim, retry, heartbeat and backpressure policy is the minimum required
for `nex-wa-evidence-consumer`?

SA-Q18
What exact source identity forms the queue idempotency key and the independent
WorkEvidence uniqueness key?

SA-Q19
Which source types are authoritative enough for approval-free background
admission?

SA-Q20
Which manual/import evidence types require stronger downstream confirmation,
without turning WA intake itself into an approval workflow?

SA-Q21
What is the minimal technical evidence-processing state vocabulary, explicitly
separate from business approval state?
```

---

# 87. Open Decision — WA Service Topology

Preferred:

```text
dedicated nex-wa service
owner-local PostgreSQL
```

Open:

```text
single API process only
vs
API + evidence consumer
```

Source Audit should decide based on event sources and operational needs.

---

# 88. Open Decision — WorkAsset Granularity

Possible models:

```text
one asset per WorkResult
one asset per Artifact
one asset per business deliverable
one asset per actor/Project/day
```

This SHALL NOT be guessed in Pre-Architecture.

Source Audit / Frozen design reconciliation is required.

---

# 89. Open Decision — Evidence Event Contract

P9 must determine whether to consume:

```text
existing generic events
new WA-specific safe projections
owner API reads
```

P9 SHOULD avoid forcing all existing P8 services to publish broad new payloads
unless necessary.

---

# 90. Open Decision — Contribution Method

Potential inputs include:

```text
WorkResult completion
Artifact creation
review/approval
duration
business outcome
Agent execution/tool facts
```

No weight or formula is frozen here.

---

# 91. Open Decision — Human Confirmation

It remains open whether P9 itself stores:

```text
candidate confirmation
```

or Golden C/EOS owns confirmation when a candidate becomes accounting effort.

Initial preference:

```text
WA = candidate
Golden C/EOS = accounting confirmation/finalization
```

---

# 92. Open Decision — NeX-AG Governance

AG is a candidate owner for:

```text
WA metric catalog governance
contribution method governance
retention policy
classification policy
```

Exact ownership should close later.

---

# 93. Open Decision — Foundation Process Scaling

Initial preference:

```text
1 x nex-wa-api
1 x nex-wa-evidence-consumer
```

The consumer process type may later scale horizontally.

The Source Audit / Contract Closure SHALL decide:

```text
claim/lease semantics
retry policy
worker heartbeat
maximum attempts
backpressure
queue depth limits
dead-letter or terminal failure treatment
```

No additional scheduler or dispatcher service is assumed.

---

# 94. P9 Invariants

```text
P9-INV-01
NeX-WA is not a scheduler.

P9-INV-02
NeX-WA is not payroll/accounting SoR.

P9-INV-03
NeX-WA supports HUMAN and AGENT actors.

P9-INV-04
Human identity remains OA-owned.

P9-INV-05
Agent identity/execution remains AE-owned.

P9-INV-06
Work coordination remains WC-owned.

P9-INV-07
Project/ProjectMember remains EOS-owned.

P9-INV-08
WA does not directly read another service database.

P9-INV-09
WA persists references and normalized evidence, not uncontrolled source copies.

P9-INV-10
Admitted evidence is immutable or explicitly superseded.

P9-INV-11
Same source fact cannot create duplicate semantic evidence.

P9-INV-12
Source correction preserves historical lineage.

P9-INV-13
Project identity is deterministic and authoritative.

P9-INV-14
LLM/model output is candidate only.

P9-INV-15
ContributionCandidate is not final MM.

P9-INV-16
ContributionCandidate is not cost.

P9-INV-17
Agent contribution is not Agent monetary cost.

P9-INV-18
No employee performance ranking is produced by Foundation.

P9-INV-19
Absence of evidence does not automatically mean zero work.

P9-INV-20
Detailed Human work evidence is privacy-controlled.

P9-INV-21
Derived candidate binds exact evidence and method version.

P9-INV-22
P8 tenant/authority/evidence invariants remain preserved.

P9-INV-23
P9 produces a clean upstream evidence boundary for Golden C.

P9-INV-24
NeX-WA implementation scope stops before compensation and Project P/L.

P9-INV-25
WA evidence intake uses the shared service-local JobQueue pattern, not AE RuntimeJob.

P9-INV-26
Initial WA Foundation Job type is limited to WA_EVIDENCE_INGEST unless a new
requirement is explicitly closed.

P9-INV-27
Queue payload contains references/hashes, not raw prompts, credentials or
unbounded business content.

P9-INV-28
Queue-level idempotency and WorkEvidence-level source idempotency are both required.

P9-INV-29
P9 Foundation does not require Kafka/RabbitMQ/NATS/Redis Streams.

P9-INV-30
P9 Foundation does not require NSL Skill implementation or Skill Pack packaging.

P9-INV-31
Authoritative WA evidence admission is a background operation and does not
require Human Approval.

P9-INV-32
The artifact creator is provenance and SHALL NOT be required to re-approve
authoritative system-generated evidence.

P9-INV-33
No Human Approval does not mean no control: source, tenant, actor, Project,
hash/version and idempotency SHALL be deterministically verified as applicable.

P9-INV-34
Ordinary system-generated evidence uses technical/admission processing states,
not business approval states.

P9-INV-35
Contribution/Effort candidates may be calculated automatically and remain
non-authoritative candidates until a downstream business boundary promotes
them.

P9-INV-36
Human/Policy approval, when required, belongs at the downstream consequential
business-authority boundary such as Golden C final effort/cost admission, not
at WA evidence registration.
```

---

# 95. Golden C Handoff Contract — Pre-Architecture Direction

After P9 closure, Golden C should re-baseline against WA.

Expected handoff:

```text
WA HumanEffortCandidate
        │
        ├─ actor_ref
        ├─ project_ref
        ├─ period
        ├─ candidate contribution
        ├─ confidence
        ├─ completeness
        ├─ evidence_set_ref/hash
        └─ method/version
        │
        ▼
Golden C
        │
        ├─ Manager / policy confirmation
        ├─ 0.05-MM conversion/finalization
        ├─ Compensation / LaborCostBasis
        ├─ Project Labor Cost
        └─ Project P/L
```

Golden C remains responsible for financial authority.

---

# 96. Golden C Document Impact

The existing Golden C documents remain valuable.

After P9, they SHOULD receive one bounded amendment rather than being rewritten
from scratch.

Expected change:

```text
Before P9:
MANUAL / IMPORT Labor Ratio

After P9:
WA_EVIDENCE_DERIVED Candidate
→ MANAGER_CONFIRMED
with MANUAL / IMPORT fallback
```

Other Golden C accounting/privacy decisions remain largely reusable.

---

# 97. Deferred Post-Foundation Extensions

The following are deliberately deferred until after WA Foundation closure:

```text
NSL-based WA query or mutation
Work Asset Skill Pack
natural-language WA operations
semantic enrichment through delegated Agents
advanced contribution analysis
external message broker
scheduler/resource optimization
```

These are not required for P9 Foundation acceptance.

---

# 98. Foundation Stop Conditions

P9 implementation SHALL stop and return to architecture review if work begins
to require:

```text
automatic task assignment
scheduling
employee ranking
performance score
salary
payroll
Project cost money
Management Voucher
Project P/L
Agent monetary cost
direct AE/WC/EOS/OA DB reads
identity duplication
silent evidence overwrite
LLM-owned contribution authority
```

These indicate scope escape.

---

# 99. Recommended Design Sequence

```text
P9 NeX-WA Pre-Architecture Decision       THIS DOCUMENT
        ↓
P9 NeX-WA Source Audit
        ↓
P9 Contract Closure
        ↓
P9 SRS
        ↓
P9 Implementation Slice Plan
        ↓
P9 Implementation
        ↓
P9 Final As-Built
        ↓
Golden C Post-NeX-WA Re-Baseline Amendment
        ↓
Golden C Implementation
```

---

# 100. P9 Exit Vision

P9 should be considered successful when NeX Platform can reliably say:

```text
For this tenant and Project,
these Human and Agent actors produced
these evidence-backed work assets
during this period,
using these authoritative source records,
and this is the reproducible contribution candidate
derived from those exact facts.
```

P9 should NOT need to say:

```text
therefore this employee costs 8,000,000 KRW on Project A
```

That is Golden C.

---

# 101. Final Decision

P9 is authorized as a bounded NeX-WA Foundation phase.

The intended architecture is:

```text
P8 Runtime / Work / Project / Evidence Foundation
        │
        ▼
NeX-WA
────────────────────────────────────
nex-wa-api
WA service_jobs
nex-wa-evidence-consumer
approval-free background evidence admission
deterministic source/tenant/actor/project verification
Work Evidence
Work Assets
Human + Agent Actor Model
Project Attribution
Provenance
Quantitative Work Facts
Contribution / Effort Candidates
        │
        ▼
Golden C
────────────────────────────────────
Human confirmation / policy
0.05-MM finalization
Compensation
Labor Cost
Management Accounting
Project P/L
```

The runtime admission rule is:

> **Authoritative work evidence is collected automatically in the background.
> Human Approval is not required to record that evidence; deterministic
> verification is required. Approval is deferred until a downstream business
> decision gives the evidence consequential authority.**

The core architectural rule is:

> **P9 shall make work measurable and traceable, not make people financially
> accountable automatically. NeX-WA provides evidence-backed Human and Agent
> contribution candidates; Golden C later converts admitted Human effort into
> deterministic, privacy-preserving Management Accounting.**
