# P7 — WC + CA/PA/EA Background Work
# Software Requirements Specification v1.0

**Document Status:** PRE-IMPLEMENTATION SRS
**Phase:** P7
**Predecessor:** P6.5 — CLOSED / P7 ENTRY AUTHORIZED
**Date:** 2026-10-17

---

## 1. Purpose

본 SRS는 NeX Platform에 Enterprise Work Coordination와
CA/PA/EA Background Agent 실행을 추가하기 위한 요구사항을 정의한다.

P7 완료 시 최소 canonical flow는 다음과 같다.

```text
IA AgentExecution
→ AgentPlan(DELEGATE_WORK)
→ deterministic validation / compile
→ WC WorkItem
→ Routing
→ Claim + Assignment
→ CA/PA/EA AgentExecution
→ Planning
→ Runtime
→ AgentResult
→ WC WorkResult
→ Parent Resume
→ Parent completion
```

---

## 2. Normative Baseline

P7 SHALL preserve without semantic rename:

```text
AgentIdentity
AgentExecution
WorkIntent
AgentContext
CapabilitySnapshot
AgentPlan
PlanValidationResult
ExecutablePlan
ExecutableStep
RuntimeJob
StepResult v1.2
AgentResult
ResultDelivery
VerifiedSkillArtifact
NSLStepExecutionBinding
BusinessOperationId READ semantics
```

P7 SHALL preserve P6.5:

```text
LLM Candidate != Execution Authority
```

---

## 3. Service Ownership

### NeX-AE

SHALL own:

```text
Agent Registry
AgentExecution
Planning / Validation / Compiler
RuntimeJob / Worker
Wait / Resume
AgentResult
ResultDelivery
```

### NeX-WC

SHALL own:

```text
WorkItem
RoutingDecision
Assignment
Claim
ClaimGeneration / lease
WorkResult
Work event outbox
```

### NeX-OA

SHALL remain security authority for:

```text
Principal
Role / scope
service trust
authorization decision
```

### NeX-AG

MAY read redacted operational projections.

AG SHALL NOT mutate WorkItem, Claim, AgentExecution, or Result.

---

# 4. Functional Requirements — Agent Registry

## P7-FR-001 — Generic Agent Identity

AE SHALL support persisted:

```text
IA
CA
PA
EA
```

using canonical `ae_agent_identity`.

No second CA/PA/EA identity table is permitted.

---

## P7-FR-002 — PA Project Identity

For `agent_type=PA`:

```text
project_id != null
```

and P7 SHALL enforce at most one ACTIVE PA for:

```text
(tenant_id, project_id)
```

A SUSPENDED/RETIRED PA SHALL NOT be eligible for routing or claim.

---

## P7-FR-003 — CA / EA Identity

CA and EA SHALL use canonical Agent Registry identities.

Their project binding MAY be null unless the selected Agent profile requires project scope.

---

## P7-FR-004 — Registry API

AE SHALL expose authenticated internal/admin operations sufficient for:

```text
register Agent
read exact Agent
list bounded eligible Agents
change status
resolve ACTIVE PA by project
```

WC SHALL use this API and SHALL NOT read the AE database.

---

# 5. Functional Requirements — WorkItem

## P7-FR-010 — WorkItem SoR

NeX-WC SHALL persist canonical WorkItem v2.1-compatible records.

Minimum active P7 fields:

```text
tenant_id
work_item_id
title
goal
work_class
state
source
requester
accountable_owner
routing_target
project_ref
completion_policy
closure_policy
trace
version
created_at
updated_at
```

---

## P7-FR-011 — Active Work Source

P7 initial runtime SHALL activate:

```text
source_type = AGENT_PLAN_STEP
```

Other Frozen source types remain schema-visible but runtime-disabled unless explicitly enabled later.

---

## P7-FR-012 — WorkItem Idempotency

One parent delegation attempt SHALL create at most one semantic child WorkItem.

Recommended identity input:

```text
tenant_id
parent_agent_execution_id
parent_executable_plan_id
parent_executable_step_id
delegation_revision
```

This idempotency is WC work-creation idempotency.

It SHALL NOT be represented as NSL WRITE IdempotencyKey.

---

## P7-FR-013 — WorkItem State Machine

P7 SHALL support at minimum:

```text
CREATED
ROUTED
ASSIGNED
IN_PROGRESS
BLOCKED
WAITING_INPUT
RESULT_SUBMITTED
REVISION_REQUESTED
CLOSED
CANCELLED
```

Unsupported transitions SHALL fail deterministically.

---

# 6. Functional Requirements — Routing

## P7-FR-020 — Deterministic Routing

Routing SHALL be deterministic with explicit reason codes.

LLM SHALL NOT make the final routing decision.

---

## P7-FR-021 — Required Agent Type

WorkItem routing MAY require exactly one of:

```text
CA
PA
EA
```

If non-null, every eligible AGENT candidate and successful claimant SHALL match it.

---

## P7-FR-022 — PA Scope

For PA routing:

```text
project_scope_ref required
project_ref required
```

The selected AgentIdentity.project_id SHALL match the WorkItem project.

---

## P7-FR-023 — Candidate Source

WC SHALL resolve Agent candidates from AE Agent Registry through authenticated service API.

Candidate selection SHALL consider at minimum:

```text
tenant
status ACTIVE
agent_type
project scope where required
required capability/profile eligibility
```

---

## P7-FR-024 — OA Authorization

Before claim authority is granted, current OA authorization SHALL be checked.

A stale route or prior authorization SHALL NOT substitute for current claim-time authorization.

---

# 7. Functional Requirements — Claim / Assignment

## P7-FR-030 — Atomic Claim

WC SHALL atomically commit:

```text
Claim
ClaimGeneration
Assignment
WorkItem state update
```

or none of them.

---

## P7-FR-031 — Claim Lease

Agent claims SHALL be leased and bounded.

Persist at minimum:

```text
claim_id
claim_generation
claimant_ref
claimant_agent_type
lease_token/hash-safe ref
lease_until
state
assignment_ref
created_at
updated_at
```

---

## P7-FR-032 — ClaimGeneration

Every reassignment/reclaim SHALL create a higher `claim_generation`.

Stale generation SHALL never start or mutate a Background AgentExecution.

---

## P7-FR-033 — ClaimExecutionHandoff

Only after atomic claim + assignment commit SHALL WC publish:

```text
ClaimExecutionHandoff v2.1
```

The handoff SHALL contain:

```text
work_item_ref
claim_ref
claim_generation
claimant_agent_ref
claimant_agent_type
project_id
assignment_ref
correlation_id
causation_id
```

---

## P7-FR-034 — Duplicate Handoff

AE SHALL consume handoff idempotently.

Same handoff/event identity SHALL create at most one child AgentExecution.

Same semantic trigger identity with different claim lineage SHALL fail closed.

---

# 8. Functional Requirements — Background Agent Admission

## P7-FR-040 — CLAIMED_WORKITEM Trigger

Background AgentExecution SHALL use:

```text
source_type = CLAIMED_WORKITEM
agent_type = CA | PA | EA
```

---

## P7-FR-041 — No Direct Background Prompt

P7 SHALL NOT admit direct PROMPT triggers for CA/PA/EA.

---

## P7-FR-042 — Claim Scope Validation

Before child AgentExecution creation, AE SHALL verify:

```text
Agent identity ACTIVE
agent_type exact match
tenant exact match
project exact match where required
claim_ref / generation / assignment present
handoff integrity
```

---

## P7-FR-043 — Historical AgentExecution Compatibility

Existing IA/PROMPT AgentExecution rows SHALL remain readable and behavior-compatible.

P7 migrations SHALL be additive/historical-row-safe.

---

# 9. Functional Requirements — Background Planning

## P7-FR-050 — WorkItem Planning Source

P7 SHALL define a bounded WorkItem planning projection.

It MAY contain:

```text
goal
work_class
required capability
project ref
allowed artifact/evidence refs
completion policy
result contract
```

It SHALL NOT copy unrestricted raw parent prompt, secrets, provider settings, or foreign DB snapshots.

---

## P7-FR-051 — Shared Planning Pipeline

CA/PA/EA SHALL reuse the P5/P6.5 planning pipeline.

```text
PlanningSource
→ WorkIntent
→ AgentContext
→ candidate generation where enabled
→ AgentPlan
→ PlanValidation
→ deterministic Compiler
```

No second Background-Agent planner framework is permitted.

---

## P7-FR-052 — Provider Authority Boundary

Remote provider output SHALL remain untrusted candidate data.

It SHALL NOT set:

```text
claimant AgentId
AssignmentId
ClaimId
ClaimGeneration
OA authorization
exact executable authority
```

---

# 10. Functional Requirements — DELEGATE_WORK

## P7-FR-060 — Activate Logical Step

P7 SHALL activate:

```text
AgentPlan.step_type = DELEGATE_WORK
```

only when its delegation contract is complete.

---

## P7-FR-061 — Delegation Contract

A canonical delegated step SHALL include bounded semantic fields for:

```text
work_class
goal
required_agent_type
required_capability
project_scope_ref
result_contract_ref
completion_policy
```

It SHALL NOT embed an actual assignee or claim.

---

## P7-FR-062 — Deterministic Compile

Only VALID AgentPlan SHALL compile DELEGATE_WORK.

Compiler SHALL emit:

```text
ExecutableStep.step_type = DELEGATE_WORK
executor_kind = WC_DELEGATE_WORK
```

The compiler SHALL remain provider-free.

---

## P7-FR-063 — Stable Child Work Identity

Compiled delegation SHALL contain or deterministically derive a stable delegation identity sufficient to make WC WorkItem creation idempotent.

Runtime UUID randomness SHALL NOT change semantic delegation identity.

---

# 11. Functional Requirements — Wait / Resume

## P7-FR-070 — WaitRegistration

AE SHALL persist one durable WaitRegistration for a delegated dependency.

Minimum:

```text
wait_id
tenant_id
agent_execution_id
executable_step_id
wait_type = WORK_RESULT
external_ref = work_item_id
result_contract_ref
state
version
created_at
satisfied_at
```

---

## P7-FR-071 — Parent State

After successful delegation:

```text
AgentExecution.state = WAITING_DEPENDENCY
phase = STEP_EXECUTION
```

No downstream step may start before dependency result validation.

---

## P7-FR-072 — External Event Inbox

AE SHALL persist external event identity before semantic handling.

Duplicate `event_id` SHALL not produce duplicate resume work.

---

## P7-FR-073 — Event / Wait Race

System SHALL converge correctly for both:

```text
wait first → event later
event first → wait later
```

No result event may be lost because of transaction ordering.

---

## P7-FR-074 — RESUME_EXECUTION

Satisfied wait SHALL enqueue exactly one:

```text
RuntimeJob.type = RESUME_EXECUTION
```

using stable dedup identity.

---

# 12. Functional Requirements — WorkResult

## P7-FR-080 — Background Result Delivery

A claimed Background AgentExecution SHALL produce a required:

```text
ResultDelivery.target_type = WC_WORK_RESULT
```

---

## P7-FR-081 — WC WorkResult Submit

AE SHALL submit result to WC through authenticated service API.

WC SHALL validate:

```text
current WorkItem
current assignment
claim_ref
claim_generation
claim ownership
result contract
current OA authorization
submission idempotency
```

---

## P7-FR-082 — WorkResult Atomic Commit

WC SHALL atomically:

```text
insert/verify WorkResult
update WorkItem → RESULT_SUBMITTED
insert WORK_RESULT_SUBMITTED outbox event
```

---

## P7-FR-083 — WorkResult Agent Lineage

When submitted by Agent, WorkResult SHALL require:

```text
source_execution_ref
claim_ref
claim_generation
assignment_ref
submitted_by=AGENT
```

---

## P7-FR-084 — ResultDelivery ACK

After WC accepts exact WorkResult identity/hash:

```text
WC_WORK_RESULT delivery → ACKNOWLEDGED
```

Background AgentExecution MAY become `SUCCEEDED`
only when every required delivery is ACKNOWLEDGED.

---

## P7-FR-085 — Parent Resume Validation

Parent AE SHALL validate:

```text
event identity
work_item match
result contract
claim generation
result outcome
current authority/freshness as required
```

before creating delegated StepResult.

---

# 13. Functional Requirements — Transport / Outbox

## P7-FR-090 — Durable Outbox

WC SHALL use durable outbox for at least:

```text
CLAIM_EXECUTION_HANDOFF
WORK_RESULT_SUBMITTED
```

---

## P7-FR-091 — Delivery Retry

Outbox delivery retry SHALL be technical retry only.

It SHALL NOT create a new WorkItem, Claim, AgentExecution, or WorkResult.

---

## P7-FR-092 — Service Authentication

WC↔AE and WC↔OA calls SHALL use existing platform service-auth patterns.

No raw token/secret in evidence.

---

# 14. Functional Requirements — Operations

## P7-FR-100 — WC Health / Ready / Version

NeX-WC SHALL expose canonical:

```text
/health
/ready
/version
```

Readiness SHALL fail closed if required PostgreSQL or authority dependencies are unavailable in protected mode.

---

## P7-FR-101 — AG Projection

WC SHALL expose metadata-safe operator projection for:

```text
WorkItem counts/states
routing outcomes
claim lease health
outbox backlog
result state
failure reason codes
```

No private work payload or credential.

---

# 15. Non-Functional Requirements

## P7-NFR-001 — Determinism

Routing, claim admission, handoff identity, event dedup, resume, and compiler authority SHALL be deterministic.

## P7-NFR-002 — Idempotency

Every cross-service mutation SHALL have explicit semantic idempotency.

Do not conflate:

```text
WC create idempotency
WC WorkResult submission idempotency
AE RuntimeJob dedup
NSL BusinessOperationId
NSL WRITE IdempotencyKey (future)
```

## P7-NFR-003 — Privacy

Operational evidence SHALL exclude:

```text
raw prompt
private document/generated text
provider endpoint/key
service token
database password/URL
hidden reasoning
storage absolute path
```

## P7-NFR-004 — Reliability

Restart of AE or WC SHALL preserve:

```text
WorkItem
Claim
Assignment
handoff delivery
AgentExecution
WaitRegistration
WorkResult
Resume dedup
```

## P7-NFR-005 — Service Ownership

No cross-service database mutation.

## P7-NFR-006 — Compatibility

P4/P5/P6/P6.5 regression SHALL remain green.

---

# 16. Negative / Adversarial Acceptance

Required cases include:

1. inactive CA claimant;
2. PA wrong project;
3. EA routed to PA-only work;
4. stale routing decision;
5. claim lease expired before handoff;
6. claim generation mismatch;
7. duplicate claim;
8. duplicate assignment;
9. duplicate handoff;
10. handoff with different semantics under same id;
11. duplicate WorkResult;
12. WorkResult from old claim generation;
13. WorkResult wrong schema;
14. event delivered before wait;
15. event delivered after wait;
16. duplicate event;
17. AE restart before event;
18. WC restart before outbox delivery;
19. WC unavailable during DELEGATE_WORK;
20. OA authorization revoked before claim;
21. OA authorization revoked before result submit;
22. provider-generated actual assignee field;
23. provider-generated forbidden claim field;
24. DELEGATE_WORK without project for PA;
25. unknown Agent profile;
26. result delivery ACK lost;
27. resume job duplicated;
28. parent cancelled while child result arrives;
29. child failed result;
30. cross-tenant WorkItem/result reference.

No negative path may create unauthorized AgentExecution or duplicate semantic work.

---

# 17. Persistence Requirements

### NeX-WC

P7 SHALL create service-local PostgreSQL persistence.

At minimum:

```text
wc_work_item
wc_routing_decision
wc_assignment
wc_claim
wc_work_result
wc_event_outbox
wc_event_delivery_attempt
```

### NeX-AE

Likely additive persistence:

```text
generalized ae_agent_identity constraints/indexes
generalized ae_agent_execution claim fields
ae_wait_registration
ae_external_event_inbox
delegation lineage / binding if not representable safely in ExecutableStep
ResultDelivery WC target support
RuntimeJob RESUME type
```

Exact schema closes at P7-CA01.

---

# 18. Initial P7 Golden Journey

```text
1. IA receives natural-language request.
2. P6.5 provider creates a PlanCandidate containing one bounded DELEGATE_WORK.
3. AE deterministic admission binds required_agent_type=PA and project.
4. Validator returns VALID.
5. Compiler emits WC_DELEGATE_WORK.
6. Parent creates durable WaitRegistration and one child WorkItem.
7. WC routes to exact ACTIVE PA for the project.
8. WC atomically claims/assigns and publishes ClaimExecutionHandoff.
9. AE creates exactly one PA AgentExecution.
10. PA plans work through existing P6.5 pipeline.
11. PA executes at least one P6 LOCAL_SKILL / NSL READ step.
12. PA creates AgentResult and required WC_WORK_RESULT delivery.
13. WC accepts WorkResult and publishes WORK_RESULT_SUBMITTED.
14. AE parent matches wait and enqueues exactly one RESUME_EXECUTION.
15. Parent DELEGATE_WORK StepResult becomes terminal.
16. Parent deterministic REPORT completes.
17. Restart/replay does not duplicate WorkItem, child execution, WorkResult, or resume.
18. Protected DB/file residue is zero.
```

---

# 19. P7 Exit Gate

P7 is complete only when:

```text
1. P7-CA01 source-backed contract closure PASS
2. NeX-WC service + PostgreSQL PASS
3. CA/PA/EA Agent Registry runtime PASS
4. deterministic routing PASS
5. atomic claim/assignment PASS
6. ClaimExecutionHandoff PASS
7. CLAIMED_WORKITEM AgentExecution PASS
8. DELEGATE_WORK compile/executor PASS
9. WaitRegistration / event inbox / RESUME PASS
10. Background Agent P6.5 planning PASS
11. Background Agent P6 NSL READ PASS
12. WC WorkResult / ResultDelivery ACK PASS
13. Parent resume PASS
14. failure/adversarial matrix PASS
15. restart/idempotency PASS
16. actual PostgreSQL protected E2E PASS
17. actual remote generation protected E2E PASS
18. P4~P6.5 regression PASS
19. repository Full Gate PASS
20. zero owned test residue
```

---

# 20. Out of Scope

```text
NSL WRITE
Approval
CommitState / VerificationStatus
UNKNOWN_COMMIT_STATE
Enterprise OS transaction
Business formal approval
Schedule / recurring work
Human executor UI
External A2A Agent
multi-host WC HA
Kafka requirement
full parallel fan-out
```

---

# 21. Definition of Done

> **P7 is done when a deterministically compiled DELEGATE_WORK step creates exactly one WC WorkItem, an authorized atomic claim starts exactly one CA/PA/EA AgentExecution, the Background Agent completes through the existing P6.5/P6 runtime, its WorkResult is durably delivered through WC, and the parent resumes exactly once without any model, service retry, or stale claim becoming execution authority.**
