# P6 Final As-Built Baseline and P7 Handoff v1.0

**Status:** FINAL / P6 CLOSED / P7 ENTRY BASELINE
**Phase Closed:** P6 — NSL READ Integration
**Next Phase:** P7 — WC + CA/PA/EA Background Work
**Observed Date:** 2026-10-16
**Platform Branch:** `transition/p4-agent-runtime-foundation`

---

## 1. Purpose

본 문서는 P6 구현, P6 Full Gate, P6-CA02 In-Process Runtime Profile 보완,
Dual-Profile acceptance, lease recovery hardening, AE transition test namespace 정규화까지
완료된 시점의 **최종 P6 As-Built baseline**을 고정하고 P7이 상속해야 할
architecture / contract / persistence / runtime / test boundary를 정의한다.

본 문서는 P6의 설계를 다시 열기 위한 문서가 아니다.

> **P7은 본 문서에 정의된 P6 baseline 위에 새로운 capability를 additive하게 확장한다.**

---

# 2. Final Source Baseline

## 2.1 NeX Platform

```text
Repository:
nurigitdev/2607_nex_platform

Branch:
transition/p4-agent-runtime-foundation

Final reviewed HEAD:
2dd3723dc3a85849a59b5b041f507667b532aa38

Commit:
refactor(tests): normalize AE transition ownership
```

이 HEAD는 P6 Runtime Profile acceptance 이후 P4~P6 AE-owned test namespace
정규화까지 포함한다.

## 2.2 NSL

P6 최초 Source-Backed READ Contract Closure는 다음 NSL baseline에서 시작했다.

```text
Original P6 source-backed baseline:
803f22aadc3946a48b05472c80b60fe11d9d9554
```

P6-CA02 In-Process integration 과정에서 Platform과 NSL의 공용 runtime dependency
호환성을 위해 NSL packaging baseline이 다음 revision으로 전진하였다.

```text
Final P6 / P7 NSL Runtime Baseline:
3b4cb198888570a857e6fb0d3aa077930bb23504

Commit:
fix(packaging): admit shared cryptography runtime
```

따라서 P7이 상속해야 할 현재 NSL v0.1 Runtime baseline은:

```text
NSL source revision = 3b4cb198888570a857e6fb0d3aa077930bb23504
package             = nex-skill-language 0.1.0
cryptography        = 46.0.7
```

이다.

`803f22a...`는 **Original P6 source-backed baseline evidence**로 유지하며,
현재 runtime admission baseline으로 사용하지 않는다.

## 2.3 Admitted NSL Wheel

```text
Wheel:
nex_skill_language-0.1.0-py3-none-any.whl

SHA-256:
290a202f540ec98291842e9281a28288cc7ac112525b6c0f02c10b8721aef21f
```

Runtime은 local source checkout을 임의 import하지 않고 admitted wheel과
stable public API를 기준으로 동작한다.

Canonical dependency boundary:

```text
AE Runtime
→ nsl.api
→ NSL public execution contracts
```

Process-Isolated compatibility path에서만 승인된 `nsl.process_isolation`
boundary를 추가로 사용한다.

AE Runtime이 NSL private implementation module에 직접 의존하는 것은 금지한다.

---

# 3. Final P6 Runtime Architecture

P6 최종 Runtime topology는 다음과 같다.

```text
PROMPT
→ AgentExecution
→ WorkIntent
→ AgentContext
→ AgentPlan
→ PlanValidation
→ ExecutablePlan
→ ExecutableStep(LOCAL_SKILL)
→ AE RuntimeJob
→ DB-Protected Tenant Dispatcher
→ AE Runtime Worker
→ LOCAL_SKILL Executor
→ VerifiedSkillArtifact
→ NSLStepExecutionBinding
→ SkillExecutionRequest
→ NSLReadBackend
→ NSL deterministic READ
→ NSLResultSummary
→ StepResult v1.2
→ AgentResult
→ ResultDelivery(PENDING)
```

---

# 4. NSL Runtime Profile Baseline

## 4.1 Default Profile

P7의 기본 Runtime profile은 다음으로 고정한다.

```text
NSL_V01_IN_PROCESS
```

Execution topology:

```text
AE Runtime Worker Process
    |
    +-- RuntimeJob Claim
    +-- StepExecutionEngine
    +-- LOCAL_SKILL Executor
          |
          +-- Artifact Resolve / Verify
          +-- SkillExecutionRequest
          +-- NSLReadBackend
                |
                +-- NSL Validation
                +-- NSL Runtime Execution
                +-- READ Tool Invocation
                +-- CHECK / EMIT
                +-- NSL Result
          |
          +-- NSLResultSummary
          +-- StepResult
```

원칙:

> **Separate Repository != Separate Runtime Process**

NSL은 독립 repository / package / quality boundary로 유지하지만,
초기 P7 Runtime에서는 AE Runtime Worker process 내부에서 실행한다.

## 4.2 Optional Compatibility Profile

다음 profile은 유지한다.

```text
NSL_V01_PROCESS_ISOLATED
```

용도:

- crash containment;
- hard timeout;
- fault isolation;
- compatibility / operational hardening.

두 profile은 동일한:

```text
NSLReadBackend
SkillExecutionRequest
NSLExecutionId
BusinessOperationId
VerifiedSkillArtifact
NSLResultSummary
StepResult v1.2
```

contract를 공유한다.

Unknown/unconfigured profile은 silent fallback하지 않고 fail closed 한다.

---

# 5. Identity Baseline

P6에서 다음 identity는 서로 다른 의미를 유지한다.

```text
AgentExecutionId
ExecutablePlanId
LogicalPlanStepId
CompiledStepKey
ExecutableStepId
NSLExecutionId
BusinessOperationId
StepResultId
AgentResultId
ResultDeliveryId
```

Mandatory non-collapse:

```text
AgentExecutionId != NSLExecutionId
ExecutableStepId != NSLExecutionId
BusinessOperationId != NSLExecutionId
BusinessOperationId != AgentExecutionId
```

P6 READ에서는:

```text
BusinessOperationId
= stable semantic operation/correlation identity

operation_fingerprint
= null
```

기술적 retry / lease reclaim / worker restart는 동일한:

```text
AgentExecutionId
ExecutablePlanId
ExecutableStepId
NSLExecutionId
BusinessOperationId
```

를 재사용한다.

Semantic replan으로 새로운 ExecutableStep이 생성되면 새로운
NSLExecutionId / BusinessOperationId를 생성한다.

---

# 6. P6 Persistence Baseline

P6 최종 migration baseline은:

```text
latest P6 migration:
2205_ae_nsl_dual_profile
```

P6-S7 시점의 historical statement인:

```text
latest = 2204_ae_nsl_backend_run
```

은 당시에는 정확했으나 **P6 Final Baseline에는 적용하지 않는다.**

## 6.1 Canonical Runtime Tables

### `ae_runtime_job`

역할:

```text
AE durable execution work SoR
```

### `ae_runtime_job_attempt`

역할:

```text
immutable RuntimeJob claim/retry/lease attempt history
```

### `service_worker_heartbeats`

역할:

```text
AE Runtime Worker lifecycle / health / active claim visibility
```

### `ae_rt_dispatch_lease`

역할:

```text
single active dispatcher leadership
+ fencing token
+ lease expiry
```

Fairness cursor나 tenant scheduling state의 별도 SoR는 두지 않는다.

### `ae_rt_job_issue`

역할:

```text
malformed RuntimeJob operational diagnostic evidence
```

P6-S1A 이후:

```text
DispatchIssueId != ReconciliationId
```

를 유지한다.

Platform-known executor이지만 현재 capable worker가 없는 경우는 malformed가 아니며:

```text
QUEUED
+ NO_CAPABLE_WORKER
```

로 유지한다.

### `ae_nsl_artifact`

역할:

```text
tenant-scoped bounded VerifiedSkillArtifact persistence
```

Raw package/signature/journal은 복제하지 않는다.

### `ae_nsl_step_execution`

역할:

```text
LOCAL_SKILL ↔ NSL logical execution durable binding
```

P6 cardinality:

```text
UNIQUE (tenant_id, executable_step_id)
```

포함:

```text
NSLExecutionId
BusinessOperationId
verified artifact ref/hash
SkillExecutionRequest ref/hash
backend_profile
execution state/result evidence
```

### `ae_nsl_backend_run`

역할:

```text
attempt-scoped NSL backend execution evidence
```

`isolation_status`라는 column name은 historical compatibility field로 유지한다.

P7에서는 다음 의미로 해석한다.

> **backend execution-boundary disposition**

즉 In-Process profile에서도 동일 field를 사용한다.

이 column 이름은 P7 entry blocker가 아니며 rename하지 않는다.

---

# 7. StepResult Baseline

Historical P5:

```text
StepResult schema = 1.1
```

P6 LOCAL_SKILL:

```text
StepResult schema = 1.2
```

Rule:

```text
non-NSL executor:
  business_operation_id = null
  operation_fingerprint = null

LOCAL_SKILL READ:
  business_operation_id = stable non-null
  operation_fingerprint = null
```

P7은 StepResult v1.2 READ semantics를 rename/reinterpret하지 않는다.

---

# 8. Dispatcher / Worker Reliability Baseline

P6에서 다음 reliability semantics가 고정되었다.

## Dispatcher

```text
one DB-protected active leader
+ fencing token
+ bounded tenant snapshot
+ oldest runnable work ordering
+ tenant_id tie-break
+ per-tenant active cap
+ global active cap
```

Claim:

```text
eligible RuntimeJob
+ referenced ExecutableStep.executor_kind
+ worker capability
+ lease CAS
= one claim transaction
```

## Worker / Lease

Runtime mutation은 exact current lease authority를 다시 확인한다.

Stale worker / expired attempt는:

```text
StepResult persist 불가
WAITING persist 불가
RuntimeJob settlement 불가
```

Worker disappearance:

```text
LEASE_EXPIRED
→ new attempt
```

으로 복구한다.

Backend success evidence를 임의 합성하지 않는다.

## Replay

```text
Common Job Replay
!=
Agent Runtime Replay
```

Dead-letter는 blind replay 권한이 아니다.

P7도 arbitrary same-step replay API를 추가하지 않는다.

---

# 9. Artifact / Context / Security Baseline

## Exact Skill Admission

```text
exact skill_id
+ exact skill_version
+ semantic hash
+ exact package
+ signature/trust evidence
→ VerifiedSkillArtifact
```

No implicit latest.

## AgentContext Projection

금지:

```text
AgentContext JSON 전체
→ NSL runtime
```

허용:

```text
typed compiled inputs
+ explicit resource refs
+ bounded principal/authority/scope/classification
+ AgentContext ref/hash
```

User/LLM output은 다음 값을 authoritative하게 생성할 수 없다.

```text
TenantId
Principal
RoleBinding
OrgScope
ProjectScope
DataClassification
PackageTrust
```

---

# 10. Result / Timeline Baseline

P6 Timeline은:

```text
canonical persisted records/evidence
→ deterministic protected read projection
```

이다.

별도 timeline SoR가 아니다.

Ordering:

```text
(event_time, phase_order, source_type_order, stable_source_id)
→ sequence
```

원칙:

- 증명되지 않은 `state_before` 생성 금지;
- 증명되지 않은 `state_after` 생성 금지;
- unavailable optional history = null;
- projection gap은 명시;
- raw prompt/response/document/credential/secret 미포함;
- NSL raw audit journal 복제 금지.

---

# 11. Result Publication Barrier

P6는 다음까지 완료한다.

```text
AgentResult
→ ResultDelivery(PENDING)
```

다음은 아직 P6 scope가 아니다.

```text
actual publication
delivery retry
publication reconciliation
ACK
final AgentExecution.SUCCEEDED
```

따라서 P7은 기존 publication ACK barrier를 우회하지 않는다.

---

# 12. Test Ownership Baseline

최종 AE transition test namespace는 owner-first 방식으로 고정한다.

```text
test_ae_p4_*
test_ae_p5_*
test_ae_p6_*
```

금지:

```text
test_p4_*
test_p5_*
test_p6_*
```

Future P7 AE-owned tests:

```text
test_ae_p7_*
```

Platform-wide integration boundary는 필요한 경우:

```text
test_platform_p7_*
```

와 같이 ownership을 구분한다.

---

# 13. Final Quality / Regression Evidence

최종 test namespace normalization 이후 Repository-wide Full Gate:

```text
14,711 passed
38 protected tests skipped
0 failures

Statement Coverage:
97.26%

Branch Coverage:
96.71%

Contract Validation:
174 schemas
236 examples
204 negative examples
7 OpenAPI documents
PASS
```

NeX-AE Slice Gate:

```text
3,948 passed
10 protected tests skipped

Statement Coverage:
98.63%

Branch Coverage:
96.86%
```

P4-P6 owner-scoped target collection:

```text
before rename: 461
after rename:  461
```

Test rename으로 regression semantic coverage가 감소하지 않았다.

---

# 14. P6-CA02 Runtime Acceptance Evidence

Final P6-CA02-S8:

```text
closure checks: 12/12 PASS
installed-wheel readiness: 8/8
timeout/crash/lease recovery: 19/19
dual-profile PostgreSQL E2E: 10/10
profile parity dimensions: 5/5
database residue: 0
```

NSL source gate:

```text
revision:
3b4cb198888570a857e6fb0d3aa077930bb23504

tests:
1,225 passed

statement coverage:
99.47%

branch coverage:
98.56%

performance gate:
PASS
```

---

# 15. P6 Closed Scope

P6 완료:

```text
Agent Runtime Worker
Tenant Dispatcher
RuntimeJob Lease / Attempt / Recovery
Planning → LOCAL_SKILL Compile
VerifiedSkillArtifact
SkillExecutionRequest
NSL v0.1 READ Integration
In-Process NSL Profile
Process-Isolated Compatibility Profile
StepResult v1.2
AgentResult
Execution Timeline
Dual-Profile E2E
Full Gate
AE Test Ownership Normalization
```

---

# 16. Deferred Beyond P6

P6에서 의도적으로 구현하지 않은 영역:

```text
WC WorkItem / Claim / Assignment
CA / PA / EA execution admission
DELEGATE_WORK execution
NSL WRITE
Approval
Checkpoint / Resume for WRITE
actual WRITE IdempotencyKey
CommitState
VerificationStatus
UNKNOWN_COMMIT_STATE reconciliation
Enterprise OS WRITE
Result Publication / ACK
WA post-work reporting
Schedule / Recurring Work
```

이들은 P7 이후의 additive evolution 영역이다.

---

# 17. P7 Non-Negotiable Inheritance

P7은 다음 P6 결정을 재설계하거나 rename하지 않는다.

```text
1. AgentExecution hierarchy
2. RuntimeJob as AE execution SoR
3. RuntimeJob Attempt / Lease authority
4. Dispatcher leadership / fencing semantics
5. ExecutableStep identity model
6. NSLExecutionId != AgentExecutionId
7. BusinessOperationId stability
8. NSLStepExecutionBinding
9. SkillExecutionRequest
10. VerifiedSkillArtifact boundary
11. NSLReadBackend abstraction
12. NSL_V01_IN_PROCESS default
13. NSL_V01_PROCESS_ISOLATED optional profile
14. StepResult v1.2 READ semantics
15. AgentContext bounded projection
16. no implicit latest Skill/version
17. Timeline as projection, not SoR
18. ResultDelivery(PENDING) ACK barrier
19. Common JobQueue != AE RuntimeJob
20. owner-first AE test namespace
```

변경이 반드시 필요하면:

```text
Controlled Amendment
→ affected E2E revalidation
→ explicit refreeze
```

를 거친다.

---

# 18. P7 Allowed Extension Direction

P7은 P6 위에 다음 capability를 additive하게 연결한다.

```text
WC WorkItem
→ Atomic Claim
→ CLAIMED_WORKITEM Trigger
→ AgentExecution
→ existing P5/P6 Planning & Runtime
```

그리고 역할 확장:

```text
IA
CA
PA
EA
```

및:

```text
DELEGATE_WORK
Background Work
Project Work
```

를 기존 Agent Runtime hierarchy에 연결한다.

P7은 두 번째 AgentExecution hierarchy, 두 번째 RuntimeJob hierarchy,
별도 NSL runtime semantics를 만들지 않는다.

---

# 19. Final P7 Handoff Baseline

```text
Platform HEAD
= 2dd3723dc3a85849a59b5b041f507667b532aa38

NSL Runtime Baseline
= 3b4cb198888570a857e6fb0d3aa077930bb23504

NSL Wheel
= nex_skill_language-0.1.0-py3-none-any.whl
= sha256:290a202f540ec98291842e9281a28288cc7ac112525b6c0f02c10b8721aef21f

cryptography
= 46.0.7

Latest P6 Migration
= 2205_ae_nsl_dual_profile

Default NSL Profile
= NSL_V01_IN_PROCESS

Optional NSL Profile
= NSL_V01_PROCESS_ISOLATED

Runtime Work SoR
= ae_runtime_job

NSL Binding SoR
= ae_nsl_step_execution

Backend Attempt Evidence
= ae_nsl_backend_run

StepResult
= schema v1.2 for P6 LOCAL_SKILL

AE Test Namespace
= test_ae_pN_*

Final Full Gate
= 14,711 passed
= Statement 97.26%
= Branch 96.71%
```

---

# 20. Closure Statement

P6는 **NSL READ를 실제 Agent Runtime의 deterministic execution capability로 통합하고,
durable RuntimeJob/Worker/Dispatcher, exact Skill trust, stable execution identity,
StepResult, timeline, dual runtime profile 및 recovery를 실제 PostgreSQL E2E와
Full Gate로 검증한 상태**로 종료한다.

P7은 이 baseline을 재설계하지 않고 다음 capability를 추가한다.

```text
WC
+ CLAIMED_WORKITEM
+ CA / PA / EA
+ DELEGATE_WORK
+ Background Work
```

> **P6 is CLOSED. P7 entry is ACCEPTED.**
