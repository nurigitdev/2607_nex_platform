# P7 — WC + CA/PA/EA Background Work
# Source Audit v1.0

**Status:** SOURCE-BACKED PRE-IMPLEMENTATION AUDIT
**Phase:** P7
**Repository:** `nurigitdev/2607_nex_platform`
**Branch:** `transition/p4-agent-runtime-foundation`
**Reviewed HEAD:** `ca7dc4333a1915bdb3abf05213ebc7fc4b4dc6c7`
**Date:** 2026-10-17

---

## 1. Audit Objective

본 문서는 P7 구현 전에 현재 source와 Frozen v2.1 target 사이의 실제 차이를 확인한다.

목표는 다음 세 가지다.

1. 이미 구현된 기반을 재사용한다.
2. Frozen contract에 있지만 runtime에 없는 부분을 명확히 식별한다.
3. P7에서 불필요한 parallel framework 또는 hidden SoR를 만들지 않는다.

---

## 2. Baseline Inheritance

### P6 final baseline

P6가 제공하는 안정된 기반:

```text
AgentExecution
RuntimeJob / Attempt
AE Runtime Worker
Dispatcher / Lease / Backpressure
ExecutablePlan / ExecutableStep
LOCAL_SKILL
VerifiedSkillArtifact
NSLStepExecutionBinding
NSL_V01_IN_PROCESS
NSL READ
StepResult v1.2
AgentResult
ResultDelivery(PENDING)
deterministic timeline projection
```

### P6.5 final baseline

P6.5가 추가로 제공하는 기반:

```text
Remote Generation Provider through MO
IntentCandidate
ContextCandidateSet
PlanCandidate
deterministic candidate admission
Prompt Registry exact version lineage
model/profile calibration
provider/adversarial fail-closed behavior
actual PostgreSQL + remote-provider E2E
```

Core invariant:

```text
LLM Candidate != Execution Authority
```

---

## 3. Current Service Topology Audit

현재 `services/`에는 다음 backend code가 존재한다.

```text
services/_shared
services/nex-ae-api
services/nex-ag
services/nex-cx
services/nex-mo
services/nex-oa
```

**Finding P7-AUD-001**

```text
services/nex-wc
= absent
```

따라서 Frozen v2.1의 Enterprise Work SoR인 NeX-WC는
현재 v1.0/P6.5 As-Built runtime에 존재하지 않는다.

### Decision

P7에서 `nex-wc`를 신규 service boundary로 추가한다.

금지:

```text
WC tables inside nex-ae database
WC WorkItem stored as AE RuntimeJob
WC Claim stored as AE worker lease
AG database used as Work SoR
```

---

## 4. Agent Identity Audit

### Database source

`2001_ae_agent_identity.sql`은 이미 다음 vocabulary를 허용한다.

```text
agent_type IN ('IA', 'CA', 'PA', 'EA')
```

그리고:

```text
PA → project_id required
IA → project_id NULL
CA / EA → current schema allows nullable project_id
```

### Runtime repository source

현재 `SqlAlchemyAgentIdentityRegistry`는:

```text
resolve_or_provision_ia()
resolve_ia()
```

만 구현한다.

insert도 고정:

```text
agent_type = IA
project_id = NULL
```

**Finding P7-AUD-002**

Machine schema / DB shape는 CA/PA/EA를 이미 수용하지만
실제 Agent Registry runtime API는 IA-only다.

### Required P7 action

```text
general Agent registry read
explicit CA/PA/EA registration/provisioning
status transition
project-scoped PA lookup
one ACTIVE PA per project constraint
eligible-agent read projection for WC
```

P7은 기존 IA principal assignment semantics를 변경하지 않는다.

---

## 5. ExecutionTrigger / AgentExecution Audit

### Python contract source

`ExecutionTriggerV21`은 이미:

```text
source_type = PROMPT | CLAIMED_WORKITEM
agent_type  = IA | CA | PA | EA
```

를 표현한다.

`CLAIMED_WORKITEM`일 때 요구:

```text
agent_type = CA | PA | EA
project_id
work_item_ref
claim_ref
assignment_ref
claim_generation
```

### Database source

`2003_ae_agent_execution.sql`은 현재:

```text
agent_type CHECK (agent_type = 'IA')
source_type CHECK (source_type = 'PROMPT')
```

으로 제한되어 있다.

### Repository source

`SqlAlchemyAgentExecutionRepository.admit_prompt()`:

```text
PROMPT + IA only
```

`AgentExecutionAdmissionService`도 IA prompt만 admit한다.

**Finding P7-AUD-003 — Critical**

Frozen trigger vocabulary는 이미 source에 있지만
실제 persistence / admission authority는 `CLAIMED_WORKITEM`을 실행할 수 없다.

### Required P7 action

historical-row-safe migration으로:

```text
agent_type constraint generalization
source_type constraint generalization
work_item_ref
claim_ref
claim_generation
assignment_ref
requester_ref
```

를 추가하고:

```text
admit_claimed_work()
```

를 별도 구현한다.

PROMPT admission과 CLAIMED_WORKITEM admission을 한 함수에서 암묵적으로 섞지 않는다.

---

## 6. AgentPlan / Compiler Audit

### AgentPlan validator

현재 `agent_plans.py`는 logical vocabulary로 이미:

```text
LOCAL_CAPABILITY
DELEGATE_WORK
AGGREGATE
REPORT
```

를 인정한다.

### P6.5 PlanCandidate

현재 live PlanCandidate path는 P6.5 범위상:

```text
LOCAL_CAPABILITY
AGGREGATE
REPORT
```

만 허용하며 `DELEGATE_WORK`를 거부한다.

### Compiler

현재 `executable_plans.py`는 명시적으로:

```text
if logical_type == "DELEGATE_WORK":
    raise ... "DELEGATE_WORK executor is unavailable in P5."
```

한다.

ExecutablePlan validator에는 future vocabulary:

```text
step_type = DELEGATE_WORK
executor_kind = DELEGATE_WORK_UNAVAILABLE
```

가 이미 존재한다.

**Finding P7-AUD-004**

P7은 새 vocabulary를 발명할 필요가 없다.
현재 intentionally-disabled `DELEGATE_WORK`를
Frozen WC contract에 맞게 활성화하면 된다.

### Required P7 action

P7 plan contract에는 delegation metadata가 필요하다.

최소:

```text
required_agent_type
required_capability
work_class
project_scope_ref
result_contract_ref
completion_policy
```

실제 claimant AgentId는 plan에 들어가지 않는다.

---

## 7. RuntimeJob / Wait / Resume Audit

### Current RuntimeJob

`runtime_jobs.py`:

```text
P4_RUNTIME_JOB_TYPES =
START_EXECUTION
CONTINUE_EXECUTION
```

`2004_ae_runtime_job.sql`도 동일하다.

흥미로운 existing columns:

```text
wait_id
reconciliation_id
result_delivery_id
publication_reconciliation_id
```

그러나 current source에는 generic durable `WaitRegistration` implementation이 없다.

**Finding P7-AUD-005**

Frozen Background Work의 핵심인:

```text
WAITING_DEPENDENCY
→ external result event
→ RESUME
```

를 runtime vocabulary는 일부 표현하지만
durable wait/event/resume SoR가 아직 없다.

### Required P7 action

추가:

```text
RESUME_EXECUTION RuntimeJob
ae_wait_registration
ae_external_event_inbox
event_id dedup
resume dedup
```

규칙:

```text
event may arrive before wait
wait may exist before event
either order must converge to one ResumeJob
```

---

## 8. Work Coordination Source Audit

현재 source/runtime에는 다음 domain object가 없다.

```text
WorkItem
RoutingDecision
Assignment
Claim
ClaimGeneration
WorkResult
WORK_RESULT_SUBMITTED
ClaimExecutionHandoff
```

Frozen v2.1에는 machine-readable contract가 존재한다.

### WorkItem v2.1

Frozen state vocabulary:

```text
CREATED
ROUTED
ASSIGNED
ACKNOWLEDGED
IN_PROGRESS
BLOCKED
WAITING_INPUT
RESULT_SUBMITTED
REVISION_REQUESTED
CLOSED
CANCELLED
```

Frozen routing profile:

```text
required_agent_type = CA | PA | EA | null
```

PA에는 `project_scope_ref` 및 `project_ref`가 필요하다.

### RoutingDecision v2.1

Candidate types:

```text
HUMAN
AGENT
EXTERNAL_AGENT
```

P7 active subset:

```text
AGENT only
CA | PA | EA
```

### ClaimExecutionHandoff v2.1

Required lineage:

```text
work_item_ref
claim_ref
claim_generation
claimant_agent_ref
claimant_agent_type
project_id
assignment_ref
correlation_id
```

### WorkResult / event

Agent submission에는 반드시:

```text
source_execution_ref
claim_ref
claim_generation
assignment_ref
```

가 필요하다.

**Finding P7-AUD-006**

Frozen target는 충분히 구체적이며,
P7은 first-principles Work Coordination redesign이 아니라
machine contract의 source-backed implementation 단계다.

---

## 9. Cross-Service Ownership Audit

### AE

Current strengths:

```text
Agent Registry table
AgentExecution
Planning/Compiler
RuntimeJob
Worker
NSL READ
AgentResult
ResultDelivery
```

P7 extension owner:

```text
CA/PA/EA registry runtime
CLAIMED_WORKITEM admission
Wait/Resume
DELEGATE_WORK executor
WC ResultDelivery publisher
```

### WC — new

Must own:

```text
WorkItem
RoutingDecision
Assignment
Claim/Lease
WorkResult
Outbox
```

### OA

Must remain:

```text
Principal / service trust
Role / scope authority
authorization decision
```

WC/AE must not duplicate OA authority into mutable local grants.

### AG

May read redacted operational projection only.

No mutation authority.

**Finding P7-AUD-007**

P7 requires new AE↔WC and WC↔OA interfaces,
but no cross-service direct DB access.

---

## 10. P6.5 Generation Reuse Audit

P6.5 `DeterministicCandidateAdmissionService` is currently chat/IA-oriented.

It can be reused conceptually, but Background Agent source differs:

```text
IA:
User Prompt + Conversation

Background Agent:
Claimed WorkItem + Work contract + Project scope
```

**Finding P7-AUD-008**

P7 should not fake a user prompt or create a second planner.

Recommended refactoring:

```text
SemanticPlanningSource
  ├─ IA_PROMPT
  └─ CLAIMED_WORKITEM
```

Both feed the same candidate/admission pipeline,
while source projection and authority derivation remain separate.

No provider call may select actual WC assignee/claim.

---

## 11. Result Publication Audit

Current P4~P6 finalization creates:

```text
AgentResult
+ required WORKSPACE_RESULT ResultDelivery(PENDING)
```

P6 intentionally did not close publication ACK.

Frozen Work Coordination requires background result submission.

**Finding P7-AUD-009**

P7 needs the first concrete non-workspace delivery target:

```text
WC_WORK_RESULT
```

Required flow:

```text
Background AgentResult
→ WC_WORK_RESULT ResultDelivery(PENDING)
→ WC WorkResult accepted
→ delivery ACK
```

This must not be simulated as direct WC DB insert from AE.

---

## 12. Current Schema / Migration Audit

Latest AE migration:

```text
2300_ae_semantic_candidate
```

Therefore P7 AE migrations can safely use a new family such as `2400_*`.

NeX-WC has no current migration history in the runtime repository,
so it needs its own independent migration chain.

Recommended:

```text
database/nex-wc/migrations/
```

with service-owned:

```text
nex_wc
nex_wc_test
nex_wc_user
```

No migration may alter the frozen v1.0 tag.

---

## 13. Current Test / Evidence Audit

Reusable discipline:

```text
pytest
boundary / robustness / worst-case
actual PostgreSQL protected smoke
remote provider protected acceptance
contract validation
Full Gate
zero residue
```

P7-specific test namespace:

```text
tests/test_ae_p7_*
tests/test_wc_p7_*
tests/test_platform_p7_*
scripts/smoke/run_p7_*
```

Protected final acceptance should use at minimum:

```text
nex_ae_test
nex_wc_test
nex_oa_test
live MO generation provider
admitted NSL wheel / P6 READ backend
```

---

## 14. Gap Register

| ID | Severity | Gap | P7 disposition |
|---|---:|---|---|
| P7-GAP-001 | P0 | No NeX-WC runtime service / Work SoR | New `nex-wc` service |
| P7-GAP-002 | P0 | AgentExecution DB rejects CLAIMED_WORKITEM | Historical-row-safe AE migration |
| P7-GAP-003 | P0 | No Claim/Assignment atomic authority | WC transaction + ClaimGeneration |
| P7-GAP-004 | P0 | No durable Wait/Resume | AE WaitRegistration + event inbox + RESUME job |
| P7-GAP-005 | P0 | No WorkResult → parent resume path | WC outbox + AE idempotent event ingest |
| P7-GAP-006 | P1 | AE Agent Registry runtime is IA-only | CA/PA/EA registry extension |
| P7-GAP-007 | P1 | DELEGATE_WORK compiler unavailable | P7 delegate contract + executor |
| P7-GAP-008 | P1 | P6.5 planning source is IA/chat-oriented | Source abstraction for claimed work |
| P7-GAP-009 | P1 | ResultDelivery has no WC publication closure | WC_WORK_RESULT publisher + ACK |
| P7-GAP-010 | P1 | No service-API candidate lookup for WC | AE Agent Registry read API |
| P7-GAP-011 | P1 | No exact OA check wired to claim/result boundaries | Source-backed OA integration |
| P7-GAP-012 | P2 | Human/external/schedule shapes exist but not runtime | Explicit defer |

No P7 implementation should begin until P0 contract decisions are closed in CA01.

---

## 15. P7-CA01 Required Source-Backed Closure

CA01 SHALL inspect and freeze exact source/API behavior for:

### AE

```text
agent_identity.py
agent_execution.py
agent_plans.py
plan_validation.py
executable_plans.py
runtime_jobs.py
step result / finalization
result delivery
semantic candidate admission
runtime worker / dispatcher
```

### OA

```text
service auth
authorization/scope check
subject / role / project authority projection
```

### new WC

Before implementation, derive exact contracts from Frozen:

```text
WorkItem
RoutingDecision
ClaimExecutionHandoff
WorkResult
WORK_RESULT_SUBMITTED
```

### Decisions CA01 must close

1. exact AE Agent Registry read/write API;
2. PA uniqueness and project rules;
3. WorkItem idempotency identity;
4. Routing candidate contract;
5. Claim/Assignment/lease transaction;
6. ClaimExecutionHandoff transport;
7. AE CLAIMED_WORKITEM persistence shape;
8. WaitRegistration / event inbox shape;
9. RESUME_EXECUTION job semantics;
10. DELEGATE_WORK AgentPlan/ExecutableStep contract;
11. child WorkResult contract;
12. WC ResultDelivery ACK semantics;
13. OA checks at claim and result submit;
14. source projection for Background Agent planning;
15. protected Golden Journey.

---

## 16. Recommended Refactoring Before Feature Work

Refactoring should precede capability activation where needed.

### AE Agent admission

Split:

```text
PromptAdmission
ClaimedWorkAdmission
```

behind common immutable `ExecutionTriggerV21`.

### Semantic planning

Split source extraction from semantic candidate generation:

```text
PlanningSourceAdapter
→ bounded semantic input
→ existing P6.5 candidate stages
```

### Result publication

Generalize target-specific publisher:

```text
ResultDeliveryPublisher
  ├─ WORKSPACE_RESULT (existing/deferred ACK)
  └─ WC_WORK_RESULT (P7 active)
```

No broad shared framework rewrite.

---

## 17. Audit Exit Decision

The current source is a strong P7 base because:

```text
Agent identity vocabulary exists
CLAIMED_WORKITEM vocabulary exists
DELEGATE_WORK vocabulary exists
RuntimeJob/Worker exists
P6.5 planning exists
P6 NSL READ exists
```

하지만 execution authority pieces are intentionally disabled/missing.

따라서 P7은:

```text
REUSE
+ GENERALIZE
+ ADD WC SoR
+ ADD WAIT/RESUME
+ ACTIVATE DELEGATE_WORK
```

로 진행한다.

> **P7 Source Audit result: READY FOR P7-CA01 CONTRACT CLOSURE / NO FEATURE IMPLEMENTATION YET.**
