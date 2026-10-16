# P6-CA02 — In-Process NSL Runtime Profile Clarification v1.0

**Status:** POST-P6 CONTROLLED ARCHITECTURE AMENDMENT
**Phase:** P6 — NSL READ Integration
**Timing:** P6 Implementation / Full Gate 완료 후, P7 진입 전
**Effect:** Runtime deployment profile clarification only

## 1. Purpose

P6 구현 완료 후 AE Runtime과 NSL의 실제 배치 구조를 재검토한 결과,
초기 운영 및 debugging 단계에서는 NSL을 별도 Server/Process로 분리하기보다
**AE Runtime Worker Process 내부에서 Library/Module 형태로 실행하는 구조**가 더 단순하고 적절하다고 판단한다.

이 변경은 P6의 다음 계약을 변경하지 않는다.

```text
AgentExecutionId
ExecutablePlanId
ExecutableStepId
NSLExecutionId
BusinessOperationId
RuntimeJob / Attempt
VerifiedSkillArtifact
SkillExecutionRequest
NSLResultSummary
StepResult v1.2
```

또한 P6의 DB schema, dispatcher, worker lease, retry/restart semantics를 변경하지 않는다.

## 2. Core Decision

P6/P7 초기 기본 Runtime Profile은 다음으로 한다.

```text
AE Runtime Worker Process
    |
    +-- RuntimeJob Claim
    +-- StepExecutionEngine
    +-- LOCAL_SKILL Executor
          |
          +-- Skill Artifact Resolve / Verify
          +-- SkillExecutionRequest Build
          +-- NSL Backend Adapter
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

즉:

> **NSL은 독립 Repository / 독립 Package로 유지하되, 초기 Runtime에서는 AE Runtime Worker Process 내부에서 실행한다.**

## 3. Repository Boundary != Process Boundary

NSL repository 분리는 계속 유지한다.

```text
nurigitdev/2608_nsl
    = Language / Compiler / Runtime / Package / Security 독립 개발

nurigitdev/2607_nex_platform
    = AE Runtime / Agent / Dispatcher / Worker / Integration
```

하지만 Runtime 배치는 다음처럼 한다.

```text
2608_nsl package / wheel
        ↓
AE Runtime Worker
        ↓
NSL public API
```

Repository 분리는 개발 및 품질 경계이며,
별도 repository라는 이유만으로 별도 Runtime Process/Server를 요구하지 않는다.

### 3.1 Package and Dependency Admission

In-Process profile은 검증된 `nex-skill-language` wheel을 AE Runtime image와
Python environment에 설치하는 경우에만 활성화한다. local source checkout을
`sys.path`에 임시 추가하는 방식은 protected development evidence에만 허용하고
배포 profile로 인정하지 않는다.

현재 dependency range에는 다음 충돌이 있다.

```text
NeX Platform: cryptography>=43,<47
NSL v0.1:     cryptography>=49,<50
```

따라서 In-Process 기본 profile 활성화 전에 두 repository가 함께 통과하는
overlapping range를 검증하고 lock/wheel을 다시 생성해야 한다. NSL package
version, source revision, wheel digest와 dependency lock digest는 worker readiness
evidence에 포함하며, package 누락 또는 revision 불일치는 fail-closed 한다.

### 3.2 P6-CA02-S1 Admission Closure

P6-CA02-S1에서 dependency 충돌과 wheel admission 선행조건을 다음처럼
해소했다.

```text
NeX Platform: cryptography>=46,<47
NSL v0.1:     cryptography>=46,<50
admitted lock: cryptography==46.0.7
```

NSL 전체 1,225개 테스트는 Platform의 `cryptography 46.0.7` 환경에서
통과했다. 승인된 NSL source revision은
`3b4cb198888570a857e6fb0d3aa077930bb23504`이며, 해당 clean revision의
`git archive`로 wheel을 두 번 독립 빌드하여 동일 digest를 확인했다.

```text
wheel: nex_skill_language-0.1.0-py3-none-any.whl
sha256:290a202f540ec98291842e9281a28288cc7ac112525b6c0f02c10b8721aef21f
```

`deployment/locks/nsl-v0.1-wheel.json`은 package version, source revision,
wheel digest, dependency 요구 범위, Platform dependency lock digest와
필수 `nsl.api` symbol을 고정한다. wheel METADATA/RECORD 무결성, lock에
고정된 cryptography version, wheel에서 직접 설치한 public API import 중
하나라도 불일치하면 admission은 실패한다.

이 Slice는 package/dependency admission만 닫는다. 기본 runtime profile의
`NSL_V01_IN_PROCESS` 전환과 worker readiness 연결은 후속 Slice 책임이다.

## 4. Initial Execution Model

한 `LOCAL_SKILL` 실행 내부는 우선 순차적으로 처리한다.

```text
RuntimeJob Claim
→ LOCAL_SKILL Executor
→ Artifact Verification
→ NSL Validation
→ NSL Execution
→ Tool READ
→ CHECK / EMIT
→ NSLResultSummary
→ StepResult
→ RuntimeJob Complete
```

초기 동시성은 NSL 내부 병렬화보다 **Worker / RuntimeJob 단위**에서 확보한다.

```text
Worker #1 → NSL Execution A
Worker #2 → NSL Execution B
Worker #3 → NSL Execution C
```

한 NSL execution 내부의 deterministic sequence는 유지한다.

초기에는 worker process 하나가 동시에 하나의 In-Process NSL execution만
수행한다. 동시성은 worker process 수를 늘려 확보하며, NSL worker session,
progress sink, audit/evidence bridge는 execution마다 새로 생성하여 mutable
runtime state를 execution 사이에서 공유하지 않는다.

## 5. Backend Interface Preservation

In-Process 배치로 변경하더라도 AE와 NSL의 Interface Boundary는 유지한다.

권장 구조:

```text
LOCAL_SKILL Executor
→ NSLReadBackend
→ nsl.api
→ SkillExecutionWorker / RuntimeEngine
```

금지:

```text
LOCAL_SKILL Executor
→ NSL private runtime internals directly
```

Backend abstraction은 계속 유지한다.

```text
NSLReadBackend
├─ NSL_V01_IN_PROCESS          ← 초기 기본 Profile
├─ NSL_V01_PROCESS_ISOLATED    ← 운영 강화 Profile
└─ future NSL_V02_BACKEND
```

따라서 향후 Process Isolation 또는 Remote Runtime으로 변경하더라도
AE의 Identity/Request/Result contract는 변경하지 않는다.

### 5.1 Dual-Profile Compatibility and Routing

신규 capability snapshot과 신규 compile은 `NSL_V01_IN_PROCESS`를 기본으로
기록한다. 기존에 저장된 `NSL_V01_PROCESS_ISOLATED` binding, RuntimeJob,
backend run evidence는 수정하거나 재작성하지 않으며 retry/restart 시 저장된
profile을 그대로 사용한다.

```text
durable binding.backend_profile
→ fail-closed backend resolver
→ exact NSLReadBackend
```

Worker는 실제로 구성되고 readiness를 통과한 profile만 capability로 광고한다.
지원하지 않는 정상 profile의 job은 `QUEUED / NO_CAPABLE_WORKER`로 유지하며,
다른 profile로 암묵적 fallback하거나 dead-letter 처리하지 않는다. 하나의
`LOCAL_SKILL` executor가 durable binding의 profile로 backend를 선택하며 AE가
NSL private module을 직접 선택하거나 호출하지 않는다.

## 6. Process Isolation Position

기존 P6-CA01에서 선택했던 `NSL_V01_PROCESS_ISOLATED`는 폐기하지 않는다.

다만 역할을 다음처럼 조정한다.

```text
초기 개발 / 안정화 / debugging
→ NSL_V01_IN_PROCESS

운영 hardening / crash isolation 필요
→ NSL_V01_PROCESS_ISOLATED

향후 별도 Runtime Service가 필요할 경우
→ 동일 NSLReadBackend 뒤에서 확장
```

따라서 Process Isolation은 **mandatory initial topology**가 아니라
**optional operational hardening profile**로 본다.

### 6.1 Timeout and Failure Semantics

In-Process profile의 timeout은 NSL Runtime/Tool의 cooperative deadline이다.
동일 process의 CPU 무한 루프, native crash 또는 강제 종료까지 격리하는 hard
timeout으로 표현하지 않는다. 이러한 crash containment가 필요하면
`NSL_V01_PROCESS_ISOLATED`를 선택한다.

기존 P6 backend run schema와 table은 유지한다. In-Process 성공은 기존
execution-boundary 호환값 `COMPLETED`로 기록하고, 포착된 NSL target error는
`TARGET_ERROR`로 기록한다. Worker process가 비정상 종료되어 terminal backend
run을 남기지 못한 경우에는 RuntimeJob lease expiry/recovery가 authoritative
recovery path가 되며 성공으로 추정하거나 terminal evidence를 합성하지 않는다.

## 7. Rationale

초기 In-Process 구조의 장점:

- AE → NSL 전체 call stack을 한 process에서 추적 가능;
- breakpoint/debugging이 단순;
- serialization/IPC/child-process failure surface 감소;
- Worker/NSL integration 문제와 Runtime 문제를 쉽게 분리 가능;
- P6/P7 초기 안정화 속도 향상;
- 별도 NSL Server 운영/배포 부담 제거.

NSL Runtime이 안정화된 이후에는 crash containment, fault isolation,
resource control 요구에 따라 Process-Isolated profile을 활성화할 수 있다.

## 8. Architecture Invariants Preserved

본 Amendment 이후에도 다음은 그대로 유지한다.

```text
AgentExecutionId != NSLExecutionId
BusinessOperationId stable across retry/restart
AgentContext whole-copy prohibited
exact Skill/version only
VerifiedSkillArtifact required
RuntimeJob is AE execution SoR
service_jobs != ae_runtime_job
LOCAL_SKILL executor is AE-owned
NSL detailed audit/evidence remains NSL-owned
no NSL WRITE in P6
```

## 9. P7 Entry Rule

P7은 다음 P6 Runtime baseline을 전제로 한다.

```text
AE Runtime Worker
→ In-Process NSL READ by default
→ same NSLReadBackend contract
→ Process-Isolated profile optional
```

P7은 NSL Process separation을 전제로 설계하지 않는다.

향후 Process/Service separation이 필요해질 경우
별도 Controlled Amendment 또는 deployment profile 변경으로 처리한다.

## 10. Verification

본 Amendment 적용 시 최소 다음을 확인한다.

- 기존 P6 Full Gate regression PASS;
- Platform/NSL dependency resolution 및 양쪽 repository quality gate PASS;
- installed NSL wheel version/source/digest readiness PASS;
- In-Process NSL READ E2E PASS;
- 동일 `NSLExecutionId` / `BusinessOperationId` 유지;
- 동일 `SkillExecutionRequest` / `NSLResultSummary` contract 유지;
- StepResult v1.2 결과 동일;
- 기존 Process-Isolated durable row의 read/retry/restart PASS;
- binding profile에 따른 exact backend routing 및 unknown profile fail-closed PASS;
- In-Process cooperative timeout과 worker lease recovery 구분 PASS;
- Process-Isolated backend는 optional compatibility path로 유지 가능;
- AE가 NSL private module에 직접 의존하지 않음.

## 11. Closure Statement

P6 이후 초기 Runtime topology는 다음으로 고정한다.

```text
Separate Repository
!=
Separate Runtime Process

AE Runtime Worker
→ LOCAL_SKILL Executor
→ NSLReadBackend
→ In-Process NSL Validation / Execution
→ NSLResultSummary
→ StepResult
```

> **P6-CA02는 Runtime deployment profile만 보완하며, P6의 계약·Identity·Persistence Architecture를 재설계하지 않는다.**
