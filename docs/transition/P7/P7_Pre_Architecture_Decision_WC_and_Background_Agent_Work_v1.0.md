# P7 — WC + CA/PA/EA Background Work
# Pre-Architecture Decision v1.0

**Status:** PRE-IMPLEMENTATION ARCHITECTURE BASELINE
**Phase:** P7 — Work Coordination + Background Agent Work
**Predecessor:** P6.5 Remote Generation Provider Integration Acceptance — CLOSED
**Successor:** P8 Controlled WRITE / Approval / Enterprise OS — not activated by this document
**Date:** 2026-10-17
**Platform Branch:** `transition/p4-agent-runtime-foundation`
**Reviewed HEAD:** `ca7dc4333a1915bdb3abf05213ebc7fc4b4dc6c7`

---

## 1. Purpose

P7의 목적은 P4~P6.5에서 완성한 단일 `AgentExecution` 중심 Runtime에
Frozen v2.1의 **Enterprise Work Coordination**과
`CA / PA / EA` Background Agent 실행을 additive하게 연결하는 것이다.

P7의 핵심 전환은 다음과 같다.

```text
P6.5
User Prompt
→ IA AgentExecution
→ Planning / Validation / Compile
→ RuntimeJob / NSL READ / Result

P7
IA or Agent Plan
→ DELEGATE_WORK
→ WC WorkItem
→ Routing
→ Atomic Claim + Assignment
→ ClaimExecutionHandoff
→ CA / PA / EA AgentExecution
→ existing P6.5 Planning
→ existing P6 Runtime / NSL READ
→ AgentResult
→ WC WorkResult
→ WORK_RESULT_SUBMITTED
→ Parent Resume
```

P7은 기존 Runtime을 대체하지 않는다.

> **WC owns Work. AE owns Agent. AgentExecution remains the execution root.**

---

## 2. Higher Authority

P7은 다음 authority hierarchy를 따른다.

```text
Integrated Frozen v2.1 Final Freeze
>
Frozen Agent v2.1 / NSL v0.2
>
Agent ↔ NSL Integration Contract v1.0
>
Platform v2.1 Architecture Decision Pack / Closure Ledger
>
Frozen WC machine-readable contracts
>
P6 Final As-Built Baseline
>
P6.5 Final As-Built Baseline
>
this P7 Pre-Architecture Decision
>
P7 Source Audit / SRS / Slice Plan
>
implementation convenience
```

Frozen 문서를 현재 source에 맞추기 위해 수정하지 않는다.

---

## 3. P7 Problem Statement

현재 As-Built source에는 이미 다음 기반이 있다.

```text
AgentIdentity schema
  IA / CA / PA / EA vocabulary

ExecutionTriggerV21
  PROMPT
  CLAIMED_WORKITEM vocabulary

AgentPlan
  DELEGATE_WORK vocabulary

ExecutablePlan
  DELEGATE_WORK step vocabulary
```

그러나 실제 Runtime authority는 아직 다음과 같이 제한되어 있다.

```text
AgentIdentity runtime resolver
= IA only

AgentExecution DB/runtime admission
= IA + PROMPT only

DELEGATE_WORK compiler
= unavailable

RuntimeJob
= START_EXECUTION / CONTINUE_EXECUTION only

WC service / WorkItem / Claim / Assignment / WorkResult
= not implemented

External WorkResult → Parent Resume
= not implemented
```

즉 P7은 새로운 개념을 발명하는 단계가 아니라,
이미 Frozen contract와 current source에 부분적으로 존재하는
**Work / Claim / Background Agent vocabulary를 실제 Runtime으로 닫는 단계**이다.

---

## 4. Final Architecture Decisions

### P7-DEC-01 — NeX-WC is a new bounded service and Enterprise Work SoR

P7에서 `nex-wc`를 독립 service boundary로 도입한다.

```text
NeX-WC
= WorkItem SoR
+ RoutingDecision
+ Assignment
+ Claim / ClaimGeneration / Lease
+ WorkResult
+ Work Event Outbox
```

NeX-WC는 다음의 SoR가 아니다.

```text
Agent Identity SoR       = AE Agent Registry
Authentication/Authority = OA
AgentExecution SoR       = AE
Business Transaction SoR = Enterprise OS (future)
NSL execution SoR        = NSL / AE integration evidence split
```

P7은 기존 5-service v1.0 release baseline을 재해석하지 않는다.
`nex-wc`는 transition branch에서 v2.1 target을 향해 추가되는 sixth backend service다.

---

### P7-DEC-02 — Agent Registry stays in AE

Canonical logical Agent identity는 계속 AE가 소유한다.

```text
ae_agent_identity
agent_type = IA | CA | PA | EA
```

P7은 현재 IA-only runtime repository를 일반화한다.

규칙:

```text
IA
= project_id NULL

PA
= project_id required
= one ACTIVE PA per (tenant_id, project_id)

CA / EA
= project_id optional unless profile/policy requires it
```

WC는 Agent를 생성하거나 Agent profile을 소유하지 않는다.
WC는 AE Agent Registry API를 통해 eligible candidate를 조회한다.

---

### P7-DEC-03 — WorkItem existence never starts AgentExecution

Frozen invariant를 그대로 적용한다.

```text
WorkItem CREATED
!= AgentExecution

RoutingDecision
!= AgentExecution

Assignment candidate
!= AgentExecution
```

Background AgentExecution은 오직 다음 이후에 시작한다.

```text
successful atomic Claim
+ actual Assignment materialization
+ committed ClaimGeneration
+ committed ClaimExecutionHandoff
```

즉:

> **Claim is execution authority handoff; WorkItem is not.**

---

### P7-DEC-04 — CLAIMED_WORKITEM is the only P7 background trigger

P7 Background Agent는 다음 trigger만 사용한다.

```text
ExecutionTrigger.source_type = CLAIMED_WORKITEM
agent_type = CA | PA | EA
```

P7에서 CA/PA/EA에 직접 PROMPT trigger를 추가하지 않는다.

IA의 user prompt path는 P6.5 그대로 유지한다.

---

### P7-DEC-05 — DELEGATE_WORK becomes executable only through WC

P7에서 `DELEGATE_WORK`를 처음 활성화한다.

```text
AgentPlan(DELEGATE_WORK)
→ deterministic validation
→ deterministic compiler
→ ExecutableStep(DELEGATE_WORK)
→ WC_DELEGATE_WORK executor
→ NeX-WC WorkItem
```

LLM은 다음을 정할 수 없다.

```text
actual assignee
claim owner
claim generation
lease
exact Agent identity
OA authorization result
```

LLM 또는 Planner는 bounded suggestion만 제공한다.

```text
required_agent_type
required_capability
work_class
goal
project selector/ref candidate
result contract hint
```

실제 Agent 선택은 WC deterministic routing + AE Registry + OA authority가 결정한다.

---

### P7-DEC-06 — Parent waits through durable WaitRegistration

`DELEGATE_WORK`는 즉시 terminal StepResult를 만들지 않는다.

첫 실행:

```text
DELEGATE_WORK ExecutableStep
→ stable WorkItem identity
→ AE WaitRegistration
→ WC WorkItem create
→ AgentExecution WAITING_DEPENDENCY
```

Child result 도착:

```text
WORK_RESULT_SUBMITTED
→ AE event inbox
→ wait match
→ result contract validation
→ current authority recheck
→ RESUME_EXECUTION RuntimeJob
→ DELEGATE_WORK StepResult terminalization
→ downstream step scheduling
```

이 구조는 event-before-wait / duplicate-event race를 견딜 수 있어야 한다.

---

### P7-DEC-07 — Add RESUME_EXECUTION as a RuntimeJob type

기존:

```text
START_EXECUTION
CONTINUE_EXECUTION
```

P7 추가:

```text
RESUME_EXECUTION
```

의미:

```text
START
= new execution progression

CONTINUE
= internal step progression / existing compatibility continuation

RESUME
= durable external wait condition satisfied
```

`RESUME_EXECUTION`은 새로운 AgentExecution을 만들지 않는다.

```text
same AgentExecutionId
same waiting ExecutableStepId
same WaitRegistrationId
```

duplicate event는 동일 dedup key로 하나의 Resume RuntimeJob만 만든다.

---

### P7-DEC-08 — WC WorkResult closes the child-to-parent boundary

Background AgentExecution 결과는 direct parent DB write가 아니다.

```text
CA/PA/EA AgentResult
→ required ResultDelivery(target=WC_WORK_RESULT)
→ authenticated AE → WC submission
→ WC WorkResult durable commit
→ WC outbox WORK_RESULT_SUBMITTED
→ AE event ingest
→ Parent resume
```

WC는 AE `AgentExecution` state를 직접 수정하지 않는다.

AE도 WC WorkItem state를 직접 수정하지 않는다.

---

### P7-DEC-09 — ResultDelivery ACK barrier is preserved, not bypassed

P6의 barrier:

```text
AgentResult
→ ResultDelivery(PENDING)
→ ACK before canonical execution success
```

P7에서 Background Agent에 대해 처음 실제 publisher를 추가한다.

```text
WC_WORK_RESULT delivery
PENDING
→ submit to WC
→ accepted WorkResult ref/hash
→ ACKNOWLEDGED
```

Background AgentExecution은 required WC delivery가 ACK되기 전 `SUCCEEDED`가 될 수 없다.

기존 IA `WORKSPACE_RESULT` publication semantics를 P7에서 임의 변경하지 않는다.

---

### P7-DEC-10 — Initial event transport is durable outbox + authenticated HTTP

P7은 Kafka 같은 신규 messaging infrastructure를 요구하지 않는다.

초기 transport:

```text
WC transaction
→ wc_event_outbox
→ WC outbox dispatcher
→ authenticated AE internal event API
→ AE idempotent event inbox
```

Transport-neutral contract는 유지한다.

향후 Kafka/A2A로 교체 가능하지만:

```text
event_id
aggregate identity
claim generation
correlation / causation
idempotency
ordering requirement
```

은 동일해야 한다.

---

### P7-DEC-11 — P6.5 generation remains untrusted for Background Agents

CA/PA/EA도 P6.5 generation path를 재사용할 수 있다.

그러나 source actor를 background Agent로 확장하더라도:

```text
LLM Candidate != Work Authority
LLM Candidate != Claim Authority
LLM Candidate != Agent Identity Authority
LLM Candidate != Execution Authority
```

는 그대로 유지한다.

Background Agent planning:

```text
Claimed WorkItem
→ bounded WorkIntent source adapter
→ AgentContext
→ optional Remote Generation Candidate
→ deterministic admission
→ AgentPlan
→ PlanValidation
→ deterministic compiler
```

Provider는 WC/Claim/Assignment를 직접 호출하지 않는다.

---

### P7-DEC-12 — P7 does not activate WRITE / Approval / Schedule

P7 명시적 Out-of-Scope:

```text
NSL WRITE
WriteIntent
actual NSL IdempotencyKey
CommitState
VerificationStatus
UNKNOWN_COMMIT_STATE
NSL Approval
Agent FORMAL_APPROVAL
WC ApprovalWorkItem
Enterprise OS transaction
Business Formal Approval
ScheduleSpec / ScheduleOccurrence
Recurring Work
External A2A Agent execution
Human Work execution
```

이들은 P7 Work/Background foundation이 닫힌 뒤 다음 controlled phase에서 활성화한다.

---

## 5. Canonical P7 Domain Boundaries

```text
┌────────────────────────────────────────────────────────────┐
│ NeX-AE                                                     │
│ Agent Registry                                             │
│ AgentExecution / Plan / Compiler / RuntimeJob              │
│ WaitRegistration / External Event Inbox                    │
│ CA/PA/EA Background Agent Runtime                          │
└───────────────┬────────────────────────────────────────────┘
                │ service API / event
                ▼
┌────────────────────────────────────────────────────────────┐
│ NeX-WC                                                     │
│ WorkItem / RoutingDecision / Assignment / Claim            │
│ WorkResult / Event Outbox                                  │
└───────────────┬────────────────────────────────────────────┘
                │ authority checks
                ▼
┌────────────────────────────────────────────────────────────┐
│ NeX-OA                                                     │
│ Principal / Role / Scope / Authorization authority         │
└────────────────────────────────────────────────────────────┘

AE background execution
  ↓
P6.5 planning
  ↓
P6 Runtime
  ↓
NSL READ
```

---

## 6. Identity Invariants

P7은 다음 identity를 절대 합치지 않는다.

```text
WorkItemId
!= AssignmentId
!= ClaimId
!= ClaimGeneration
!= AgentId
!= AgentExecutionId
!= RuntimeJobId
!= ExecutableStepId
!= NSLExecutionId
!= AgentResultId
!= WorkResultId
!= ResultDeliveryId
!= WaitRegistrationId
!= EventId
```

Parent / Child:

```text
Parent AgentExecutionId
1:N Child WorkItemId

Claimed WorkItem
1:1 active Assignment
1:1 active ClaimGeneration

one committed claim handoff
→ at most one Child AgentExecution
```

---

## 7. Initial P7 Supported Profile

P7 v1.0 transition implementation의 최소 supported profile:

```text
Work source
= AGENT_PLAN_STEP only

Assignee type
= AGENT only

Agent types
= CA | PA | EA

Routing
= deterministic exact candidate eligibility

Concurrency
= existing AE serial-ready execution
  max_parallel_steps = 1

Work result
= reference-oriented bounded result

Provider
= P6.5 MO generation path

Execution
= existing P6 Runtime + NSL READ

Transport
= authenticated HTTP + durable outbox/inbox
```

Frozen schema에 존재하더라도 다음은 P7 초기 runtime에서 disabled:

```text
HUMAN assignee
EXTERNAL_AGENT
SCHEDULE source
multi-child parallel fan-out
Approval WorkItem
```

---

## 8. Golden Journey

P7의 대표 Golden Journey는 Project Agent delegation으로 고정한다.

```text
User IA Prompt
→ P6.5 Intent/Context/Plan
→ Plan includes DELEGATE_WORK(required_agent_type=PA)
→ deterministic validation / compile
→ Parent DELEGATE_WORK step
→ WC child WorkItem
→ deterministic routing
→ ACTIVE PA for exact project
→ atomic claim + assignment
→ ClaimExecutionHandoff
→ PA AgentExecution(CLAIMED_WORKITEM)
→ WorkItem-based intent/context
→ P6.5 plan candidate
→ deterministic compile
→ P6 LOCAL_SKILL
→ NSL READ
→ PA AgentResult
→ WC_WORK_RESULT delivery
→ WC WorkResult
→ WORK_RESULT_SUBMITTED
→ Parent Wait match
→ RESUME_EXECUTION
→ Parent DELEGATE_WORK StepResult
→ Parent REPORT
→ Parent AgentResult
```

Golden READ는 기존 P6 source-backed NSL READ fixture를 재사용하는 것을 우선한다.

---

## 9. Failure / Recovery Invariants

반드시 fail closed:

```text
wrong tenant
wrong project
wrong required_agent_type
inactive Agent
retired Agent
PA project mismatch
stale routing decision
claim generation mismatch
expired claim
duplicate claim
duplicate handoff
duplicate WorkResult
duplicate event
result schema mismatch
unknown result contract
event before wait
wait before event
AE restart
WC restart
event dispatcher retry
ResultDelivery retry
provider failure
NSL failure
```

금지:

```text
WorkItem only → AgentExecution start
Routing only → AgentExecution start
Claim without committed assignment → handoff
duplicate event → duplicate RESUME
lost ACK → duplicate semantic WorkResult
LLM-selected actual assignee
cross-service DB mutation
```

---

## 10. Persistence Direction

### NeX-WC

Recommended first migration family:

```text
1000_wc_work_item
1001_wc_assignment_claim
1002_wc_work_result_outbox
```

Logical tables:

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

Recommended next migration family after 2300:

```text
2400_ae_background_agent_identity
2401_ae_claimed_work_execution
2402_ae_wait_resume
2403_ae_delegate_work
2404_ae_wc_result_delivery
```

Exact migration count/names are subject to P7-CA01 source-backed closure,
but P7 SHALL not overload unrelated existing tables with hidden semantics.

---

## 11. Rollout

Recommended:

```text
NEX_WC_RUNTIME_MODE=disabled|shadow|required
NEX_AE_BACKGROUND_AGENT_MODE=disabled|shadow|required
```

Rules:

- default remains `disabled` until protected acceptance;
- `shadow` may compute routing without claim/execution;
- `required` fails closed;
- no silent fallback from required WC path to local direct Agent execution;
- P6.5 IA path remains independently usable.

---

## 12. Architecture Exit Criteria

P7 implementation may start only after the Source Audit closes:

1. exact current AE constraint gaps identified;
2. Frozen WC contracts extracted and validated;
3. WC service ownership confirmed;
4. Agent Registry API boundary confirmed;
5. OA authorization boundary confirmed;
6. WorkItem/Claim/Assignment identity fixed;
7. Wait/Resume/event race policy fixed;
8. DELEGATE_WORK plan/compiler contract fixed;
9. WorkResult / ResultDelivery ACK mapping fixed;
10. migration and rollback boundaries fixed.

---

## 13. Final Principle

```text
LLM plans work.
WC owns work.
OA authorizes actors.
AE owns agents and execution.
NSL executes deterministic skills.
```

And:

> **A Background Agent starts because a valid Work claim was committed — not because a model decided to run it.**
