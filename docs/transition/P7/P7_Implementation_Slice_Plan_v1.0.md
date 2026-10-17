# P7 — WC + CA/PA/EA Background Work
# Implementation Slice Plan v1.0

**Status:** IMPLEMENTATION PLAN
**Phase:** P7
**Entry:** P6.5 CLOSED / P7 ENTRY AUTHORIZED
**Exit:** P7 Background Work Golden Journey CLOSED
**Date:** 2026-10-17

---

## 1. Execution Principle

P7 SHALL follow:

```text
Pre-Architecture Decision
→ Source Audit
→ CA01 Contract Closure
→ Refactoring First
→ bounded Slice implementation
→ unit / contract / regression
→ protected PostgreSQL E2E
→ protected Remote Provider E2E
→ Full Gate
→ Final As-Built / next-phase handoff
```

Non-negotiable:

```text
Read Before Write
Refactoring Before Feature
Frozen Preservation
No Cross-Service DB Mutation
No Hidden SoR
No LLM Execution Authority
No Phase Leakage into WRITE/Approval/Schedule
```

---

## 2. Canonical Slice Sequence

```text
P7-CA01
WC / Agent / Claim / Wait / Result Contract Closure

→ P7-S1
NeX-WC Service + WorkItem Foundation

→ P7-S2
AE CA/PA/EA Agent Registry Runtime

→ P7-S3
WC Deterministic Routing + Atomic Claim / Assignment

→ P7-S4
ClaimExecutionHandoff + AE CLAIMED_WORKITEM Admission

→ P7-S5
DELEGATE_WORK Compile / Executor + Durable Wait Foundation

→ Checkpoint Gate

→ P7-S6
WC WorkResult + AE Event Inbox / RESUME_EXECUTION

→ P7-S7
Background Agent Planning + P6 Runtime Integration

→ P7-S8
Failure / Restart / Idempotency / Delivery Hardening

→ P7-S9
Actual PostgreSQL + Remote Provider Golden B E2E / P7 Closure

→ Repository Full Gate
```

---

## 3. P7-CA01 — Source-Backed Contract Closure

### Goal

Frozen WC contract와 current P6.5 source를 machine-level로 연결한다.

### Required Audit

AE:

```text
AgentIdentity
AgentExecution
AgentPlan
PlanValidation
Compiler
RuntimeJob
Step engine
ResultDelivery
P6.5 semantic candidate admission
P6 worker/dispatcher
```

OA:

```text
service auth
authorization
scope/project authority
```

Frozen WC:

```text
WorkItem v2.1
RoutingDecision v2.1
ClaimExecutionHandoff v2.1
WorkResult v2.1
WORK_RESULT_SUBMITTED v2.1
wc_protocols_v2_1
```

### Decisions to Close

1. `nex-wc` package/service layout;
2. WorkItem storage profile;
3. WorkItem creation idempotency;
4. Agent Registry service API;
5. PA project uniqueness;
6. Routing policy inputs;
7. claim/assignment transaction;
8. lease/reclaim rules;
9. handoff outbox/inbox;
10. CLAIMED_WORKITEM AE persistence;
11. DELEGATE_WORK metadata schema;
12. WaitRegistration schema;
13. RESUME_EXECUTION job semantics;
14. WorkResult submission/ACK;
15. Background planning source adapter;
16. Golden Journey exact fixture.

### Deliverables

Recommended:

```text
P7_CA01_Source_Backed_WC_Background_Agent_Contract_Closure_v1.0.md

contracts/
  p7-work-item-v2.1.schema.json
  p7-routing-decision-v2.1.schema.json
  p7-claim-execution-handoff-v2.1.schema.json
  p7-work-result-v2.1.schema.json
  p7-work-result-submitted-v2.1.schema.json
  p7-delegation-spec-v1.schema.json
  p7-wait-registration-v1.schema.json
```

### Exit

No open P0/P1 contract ambiguity.

No P7 feature Slice before CA01 PASS.

---

## 4. P7-S1 — NeX-WC Service + WorkItem Foundation

### Goal

새 sixth backend service로 Work SoR를 구현한다.

### Implementation

Create:

```text
services/nex-wc/
database/nex-wc/
contracts/openapi/nex-wc/
```

Baseline endpoints:

```text
/health
/ready
/version

POST /api/v1/work-items
GET  /api/v1/work-items/{id}
GET  /api/v1/work-items/{id}/status
```

Persistence:

```text
wc_work_item
wc_routing_decision
wc_event_outbox
```

Work source initially:

```text
AGENT_PLAN_STEP
```

### Tests

- schema validation;
- state transitions;
- duplicate create same semantics;
- duplicate create different semantics;
- tenant isolation;
- source lineage;
- PostgreSQL migration/restart;
- zero residue.

### Exit

WorkItem is durable and service-owned with no AE DB dependency.

---

## 5. P7-S2 — AE CA/PA/EA Agent Registry Runtime

### Goal

Frozen AgentIdentity vocabulary를 actual runtime으로 활성화한다.

### Implementation

Generalize AE Agent Registry:

```text
register_agent()
get_agent()
list_eligible_agents()
set_agent_status()
resolve_active_pa(project_id)
```

Add PA invariant:

```text
one ACTIVE PA per tenant/project
```

Protected internal read API for WC.

Do not change existing IA principal assignment behavior.

### Tests

- CA registration;
- PA requires project;
- duplicate active PA blocked;
- PA project lookup;
- EA registration;
- suspend/retire;
- WC service-token scope;
- cross-tenant denial;
- restart persistence.

### Exit

WC can resolve metadata-safe eligible CA/PA/EA candidates through AE service API.

---

## 6. P7-S3 — Deterministic Routing + Atomic Claim / Assignment

### Goal

WorkItem에서 actual execution authority를 생성하기 전 WC routing/claim을 닫는다.

### Flow

```text
WorkItem
→ RoutingContext
→ AE Agent Registry candidates
→ OA current authorization
→ deterministic RoutingDecision
→ atomic Claim + Assignment
```

### Persistence

Add:

```text
wc_assignment
wc_claim
```

### Required Rules

```text
required_agent_type exact match
PA project exact match
ACTIVE Agent only
one active claim generation
lease bounded
reclaim increments generation
```

### Tests

- exact candidate selection;
- unavailable candidate;
- wrong agent type;
- wrong PA project;
- OA deny;
- claim race;
- lease expiry/reclaim;
- stale generation;
- concurrent workers;
- restart.

### Exit

A claim is an explicit durable execution-authority handoff candidate.

---

## 7. P7-S4 — ClaimExecutionHandoff + AE CLAIMED_WORKITEM Admission

### Goal

committed WC claim을 canonical child AgentExecution으로 연결한다.

### WC

After claim commit:

```text
wc_event_outbox
event = CLAIM_EXECUTION_HANDOFF
```

### AE

Generalize historical-safe AgentExecution persistence.

Implement:

```text
admit_claimed_work()
```

Required checks:

```text
CA|PA|EA
ACTIVE Agent
tenant
project
claim_ref
claim_generation
assignment_ref
handoff idempotency
```

### Child trigger

```text
source_type = CLAIMED_WORKITEM
```

### Tests

- exact handoff;
- duplicate handoff;
- semantic conflict;
- wrong tenant/project;
- inactive agent;
- stale claim generation;
- PA mismatch;
- restart;
- no direct WorkItem → execution shortcut.

### Exit

One committed claim creates at most one child AgentExecution.

---

## 8. P7-S5 — DELEGATE_WORK Compile / Executor + Durable Wait

### Goal

Parent AgentExecution이 child Work를 만들고 durable wait에 진입하도록 한다.

### Planning

Extend P7 PlanCandidate / AgentPlan with delegation metadata.

Activate:

```text
DELEGATE_WORK
```

### Compiler

Compile:

```text
step_type = DELEGATE_WORK
executor_kind = WC_DELEGATE_WORK
```

No actual claimant identity at compile time.

### Executor

First invocation:

```text
stable child WorkItem id
→ persist WaitRegistration
→ call WC create WorkItem idempotently
→ parent WAITING_DEPENDENCY
```

Add:

```text
ae_wait_registration
```

### Checkpoint Gate

After S5 run:

```text
P4~P6.5 regression
AE + WC Slice tests
contract validation
statement / branch thresholds
```

### Exit

Parent can safely delegate and wait without faking a terminal result.

---

## 9. P7-S6 — WorkResult + Event Inbox / RESUME_EXECUTION

### Goal

Background result가 Parent continuation을 정확히 한 번 일으키도록 한다.

### WC

Implement:

```text
POST /api/v1/work-items/{id}/results
```

Atomic:

```text
WorkResult
+ WorkItem RESULT_SUBMITTED
+ WORK_RESULT_SUBMITTED outbox
```

### AE

Add:

```text
ae_external_event_inbox
RuntimeJob type RESUME_EXECUTION
```

Flow:

```text
event ingest
→ event_id dedup
→ wait match
→ result contract validation
→ current authority check
→ one RESUME_EXECUTION
```

### Race Tests

- event before wait;
- wait before event;
- duplicate event;
- restart between event persistence and resume enqueue;
- duplicate resume enqueue;
- parent cancelled;
- result schema invalid.

### Exit

External result events are durable, replay-safe, and cannot cause duplicate semantic execution.

---

## 10. P7-S7 — Background Agent Planning + Existing Runtime Integration

### Goal

CA/PA/EA child execution이 P6.5 + P6 path를 그대로 사용하도록 한다.

### Refactor

Introduce bounded planning source abstraction:

```text
IA_PROMPT
CLAIMED_WORKITEM
```

Reuse:

```text
Intent / Context / Plan candidate stages
PlanValidation
Compiler
RuntimeJob worker
LOCAL_SKILL
NSL READ
StepResult
AgentResult
```

### Result Publication

For claimed work:

```text
AgentResult
→ required WC_WORK_RESULT ResultDelivery
→ WC submission
→ ACK
```

### Tests

- CA background execution;
- PA project execution;
- EA background execution;
- provider lineage;
- no provider-selected claimant;
- NSL READ continuity;
- WC delivery ACK;
- child success only after ACK.

### Exit

One claimed Agent can run a real background plan end-to-end.

---

## 11. P7-S8 — Failure / Restart / Idempotency Hardening

### Goal

Cross-service failures가 duplicate Work/Execution/Result/Resume를 만들지 않음을 증명한다.

### Failure Matrix

```text
WC unavailable
AE unavailable
OA unavailable
MO provider timeout/429/5xx
claim lease expires
handoff delivery fails
handoff ACK lost
child Agent restart
NSL failure
WorkResult submit timeout
WorkResult accepted but response lost
result event delivery retry
event ACK lost
parent resume crash
parent cancelled
```

### Required Proof

No duplicate:

```text
WorkItem
Assignment
active ClaimGeneration
Child AgentExecution
WorkResult
Resume RuntimeJob
Parent StepResult
```

### Tests

boundary / robustness / worst-case + protected PostgreSQL failure injection.

### Exit

Cross-service retry remains technical and identity-preserving.

---

## 12. P7-S9 — Actual PostgreSQL + Remote Provider Golden B E2E

### Goal

P7 전체 architecture를 actual integration으로 닫는다.

### Protected Components

At minimum:

```text
nex_ae_test
nex_wc_test
nex_oa_test
MO live generation provider
admitted NSL wheel
P6 NSL_V01_IN_PROCESS
```

### Golden B

Recommended:

```text
IA prompt
→ provider PlanCandidate with PA delegation suggestion
→ deterministic DELEGATE_WORK compile
→ WC WorkItem
→ exact Project PA route/claim
→ PA AgentExecution
→ provider background planning
→ LOCAL_SKILL / NSL READ
→ PA AgentResult
→ WC WorkResult
→ parent resume
→ deterministic parent report
```

### Acceptance Evidence

Record metadata only:

```text
source revision
migration heads
model profile/revision
prompt versions
WorkItemId hash-safe lineage
ClaimGeneration
AgentExecution counts
RuntimeJob counts
NSL run counts
WorkResult count
resume count
cleanup counts
```

Never record secrets/raw prompts/model output/private business content.

### Closure

Required:

```text
focused regression PASS
P7 Slice Gate PASS
Checkpoint evidence PASS
protected PostgreSQL PASS
remote provider PASS
restart/dedup PASS
contract validation PASS
Repository Full Gate PASS
zero residue
```

### Exit

Create:

```text
P7_Final_AsBuilt_Baseline_and_P8_Handoff_v1.0.md
```

---

## 13. Migration Plan

Provisional only until CA01.

### WC

```text
1000_wc_work_item
1001_wc_assignment_claim
1002_wc_work_result_outbox
```

### AE

```text
2400_ae_background_agent_identity
2401_ae_claimed_work_execution
2402_ae_wait_resume
2403_ae_delegate_work
2404_ae_wc_result_delivery
```

Rule:

- additive;
- historical P4~P6.5 rows remain valid;
- no destructive rename;
- no cross-service FK.

---

## 14. Quality Gates

### Every Slice

```text
focused unit tests
owning service regression
changed-source statement + branch coverage
contract fixtures
git diff --check
```

### Checkpoint — after S5

```text
AE regression
WC regression
platform regression
contract validation
selected PostgreSQL smoke
```

### Closure

```text
protected P7 E2E
Repository Full Gate
```

Protected provider/database tests may remain opt-in in ordinary Full Gate,
but fresh protected evidence is mandatory for P7 closure.

---

## 15. Test Design

Mandatory automated methods:

```text
boundary value analysis
robustness
worst-case
concurrency race
restart
idempotency
adversarial authority
privacy leakage
```

DB tests reset isolated test state and verify residue.

---

## 16. Expected New / Modified Areas

### New

```text
services/nex-wc/
database/nex-wc/
contracts/openapi/nex-wc/
tests/test_wc_p7_*
scripts/smoke/run_p7_*
```

### Modified AE

Likely:

```text
agent_identity.py
agent_execution.py
agent_plans.py
plan_candidate_generation.py
plan_validation.py
executable_plans.py
runtime_jobs.py
step execution/finalization
result delivery
semantic_candidate_admission.py
runtime worker/dispatcher
main/runtime composition
```

---

## 17. Commit Strategy

One semantic Slice per commit after regression.

Recommended messages:

```text
docs(p7): close WC background-work contracts
feat(wc): add durable work-item foundation
feat(ae): activate background agent registry
feat(wc): add deterministic routing and claims
feat(ae): admit claimed-work executions
feat(ae): activate delegate-work waits
feat(wc): publish durable work results
feat(ae): resume parent work from WC results
test(p7): harden background work recovery
test(p7): close Golden B background-agent acceptance
```

---

## 18. Rollback

Before P7 required mode:

```text
disable WC/background-agent rollout
retain P6.5 IA path
do not delete P7 durable rows automatically
```

Rollback SHALL never reinterpret a WC WorkItem as an AE RuntimeJob or vice versa.

---

## 19. P8 Handoff Boundary

P7 completion may authorize a later phase for:

```text
NSL WRITE
Approval
Enterprise OS
Commit/Verification/Reconciliation
```

P7 SHALL NOT pre-implement those semantics.

---

## 20. Final Principle

```text
DELEGATE_WORK creates Work.
Claim creates execution authority.
AgentExecution performs the work.
WorkResult returns the result.
Resume continues the parent.
```

Everything else must preserve those identities.
