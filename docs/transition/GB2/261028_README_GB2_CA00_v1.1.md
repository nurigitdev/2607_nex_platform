# GB2-CA00 — Platform Runtime Internalization & Smoke-to-Product Promotion

**Status:** PRE-IMPLEMENTATION DOCUMENT SET / v1.1 / GB2-CA00A RECONCILED
**Program:** NeX Platform v2.1
**Gate:** GB2-CA00
**Successor:** Golden B v2 — Manufacturing Delegation Full Journey
**Date:** 2026-10-28

---

## 1. Purpose

이 디렉터리의 GB2-CA00 문서들은 Golden B v2 구현에 들어가기 전에
반드시 먼저 닫아야 하는 **Platform Runtime 내재화 선행 Gate**를 정의한다.

핵심 문제는 다음과 같다.

```text
Implemented Capability
!=
Installed Product Runtime
```

P4~P9 동안 개별 기능은 충분히 구현되고 테스트되었지만,
P8-DEMO를 별도 branch에서 실제 release/설치형 runtime으로 준비하는 과정에서
다음과 같은 gap이 확인되었다.

```text
Smoke/Demo에서는 동작
        ↓
하지만
        ↓
current Platform process topology에서는 자동 연결되지 않음
```

대표적으로:

```text
AE Agent Runtime worker
WC event-delivery worker
EOS outbox publisher
generic runtime composition
domain activation
external dependency provisioning/readiness
```

등이 Demo/Smoke layer에 남아 있거나 fixture/hard-coding을 통해
기능이 연결되는 경우가 있었다.

GB2-CA00의 목적은 이러한 gap을 먼저 Platform 내부로 승격한 뒤
Golden B v2가 **제조 업무 자체에만 집중할 수 있는 상태**를 만드는 것이다.

---

# 2. Required Reading Order

GB2-CA00 문서는 다음 순서로 읽는다.

## 1) Source Audit / Pre-Architecture Decision

```text
261028_GB2_CA00_Platform_Runtime_Internalization_and_
Smoke_to_Product_Promotion_Audit_v1.1.md
```

먼저 이 문서를 읽는다.

이 문서는:

```text
현재 source-backed 상태
문제의 원인
Demo/Smoke와 Product Runtime의 차이
5개 핵심 개선 영역
Platform 승격 원칙
금지사항
목표 architecture
```

를 정의한다.

이 문서가 **Why / What**에 해당한다.

---

## 2) Pre-Implementation Consistency Closure

```text
261028_GB2_CA00A_Pre_Implementation_Document_
Consistency_Closure_v1.0.md
```

두 번째로 읽는다.

이 문서는 version/path 정합성, Audit 단계의 비정규 예비 work package와
canonical S01~S20의 관계, worker component evidence 등급, owner-owned
dependency readiness 재사용 경계를 확정한다.

---

## 3) Implementation Slice Plan

```text
261028_GB2_CA00_Platform_Runtime_Internalization_
Implementation_Slice_Plan_v1.1.md
```

세 번째로 읽는다.

이 문서는 Source Audit/PAD에서 정의한 5개 개선 영역을
실제 구현 순서로 분해한다.

```text
S01 ~ S20
```

의 bounded Slice와:

```text
Slice Gate
Checkpoint Gate
Full Gate
Protected Acceptance
Final As-Built
```

를 정의한다.

이 문서가 **How / In What Order**에 해당한다.

---

# 3. Document Relationship

문서 관계는 다음과 같다.

```text
Golden B v2 Design Draft v0.1
        │
        │ "실제 제조 Full Journey를 만들기 전에
        │  Platform runtime 자체를 먼저 확인해야 한다"
        ▼
GB2-CA00 Source Audit / PAD
        │
        │ 현재 gap과 target architecture 정의
        ▼
GB2-CA00A Consistency Closure
        │
        │ version/path/evidence/readiness 경계 정합화
        ▼
GB2-CA00 Implementation Slice Plan
        │
        │ S01 ~ S20
        ▼
GB2-CA00 Final As-Built
        │
        │ CLOSED / PASS
        ▼
Golden B v2 Implementation
```

---

# 4. Canonical Five Workstreams

GB2-CA00은 다음 5개 workstream을 닫는다.

```text
WS1
AE Runtime / WC Delivery / EOS Outbox worker를
current Platform process topology로 승격

WS2
p8_demo_runtime_composition을
generic installed runtime factory로 추출

WS3
p8_demo_semantic_activation의 fixture 기반 activation을
DomainIntentActivatorRegistry 기반으로 일반화

WS4
Smoke runner가 runtime transition을 만드는 것을 금지하는
Golden Journey testing contract 도입

WS5
RustFS / OpenBao / provider bootstrap을
deployment provisioning/readiness contract로 분리
```

---

# 5. Core Platformization Principle

GB2-CA00에서 가장 중요한 원칙은 다음과 같다.

> **Smoke should prove that the Platform works;
> Smoke must not be the thing that makes the Platform work.**

즉:

```text
기능을 Smoke에서 호출할 수 있음
!=
Platform에 내재화됨
```

Platform-integrated capability로 인정받기 위해서는:

```text
installed process
canonical runtime composition
admitted API/runtime contract
durable state transition
restart/recovery
```

를 통해 실제로 실행되어야 한다.

---

# 6. Fixture Rule

Fixture 자체는 금지하지 않는다.

허용:

```text
Project
Human
Agent
business master
manufacturing status
account master
external source facts
```

금지:

```text
pre-created WorkItem
pre-created Claim
pre-created AgentExecution
pre-approved Approval
pre-created AgentResult
pre-ACKed ResultDelivery
pre-created WorkResult
pre-created WA evidence
```

따라서:

```text
Business Source Fixture = ALLOWED

Runtime Transition Fixture = FORBIDDEN
```

이다.

---

# 7. Current Source-Backed Major Gaps

현재 source 기준으로 가장 중요한 gap은 다음과 같다.

```text
P0-01
current Platform missing AE Agent Runtime worker

P0-02
current Platform missing WC event-delivery worker

P0-03
current Platform missing EOS outbox publisher

P0-04
generic installed AE runtime composition absent

P0-05
product semantic admission depends on p8_demo_semantic_activation

P0-06
Golden Journey can be falsely accepted through test-side transition
```

그리고 dependency 영역에서는:

```text
OpenBao
RustFS / S3-compatible storage
live generation provider
```

의 provisioning/readiness가 Demo runner 중심으로 남아 있다.

---

# 8. Current → Target Topology

현재 P9 기준:

```text
artifacts = 9
processes = 17
```

GB2-CA00 target:

```text
artifacts = 9
processes = 20
```

추가되는 current Platform process:

```text
nex-ae-agent-runtime-worker
nex-wc-event-delivery-worker
nex-eos-outbox-publisher
```

새 OCI artifact는 만들지 않는다.

기존:

```text
nex-ae-runtime
nex-wc-runtime
nex-eos-runtime
```

을 재사용한다.

---


# 8A. NeX-WA Worker as the Platformization Reference

Current P9 Platform의 `17 processes`에는 이미:

```text
nex-wa-evidence-consumer
```

가 포함되어 있다.

이 worker는:

```text
current process manifest
deployment artifact binding
canonical packaged entrypoint
job_claiming capability
PostgreSQL persistence
heartbeat/readiness
fenced recovery
restart/idempotency
installed acceptance
```

을 갖춘 first-class Platform worker이다.

따라서 GB2-CA00의 목표를 다음 한 문장으로 요약한다.

> **P9에서 NeX-WA worker에 적용한 수준의 first-class runtime
> integration을, P8-DEMO에서만 설치형으로 존재했던 AE/WC/EOS domain
> workers에도 동일한 수준으로 승격해서 Platform에 내재화한다.**

NeX-WA worker는 이번 승격 대상이 아니다.

GB2-CA00에서 추가되는 process는 정확히:

```text
nex-ae-agent-runtime-worker
nex-wc-event-delivery-worker
nex-eos-outbox-publisher
```

세 개이다.

따라서:

```text
17 [already includes WA worker]
+ 3 [AE/WC/EOS]
= 20 target processes
```

이다.

---

# 9. Implementation Bands

Implementation Slice Plan은 다음 네 band로 구성된다.

```text
Band A
Canonical Runtime Composition / Worker Promotion
S01 ~ S08

Band B
Domain Activation Productization
S09 ~ S11

Band C
Testing Contract / Dependency Readiness
S12 ~ S16

Band D
Installed Current Platform Acceptance / Freeze
S17 ~ S20
```

---

# 10. Key Slice Milestones

주요 milestone은 다음과 같다.

```text
S03
Generic AE Installed Runtime Composition

S05
AE Agent Runtime Worker Promotion

S06
WC Event Delivery Worker Promotion

S07
EOS Outbox Publisher Promotion

S08
Current Platform Topology Closure
→ 9 artifacts / 20 processes
→ CLOSED; current CLI default, protected 8-DB topology acceptance

S09
DomainIntentActivatorRegistry
→ CLOSED; deterministic registry and domain-agnostic semantic admission

S10
Golden A Product Activator
-> CLOSED; tenant-scoped versioned finance authority profile, no generic Demo fixture dependency

S12
Golden Journey Testing Contract

S13~S16
Dependency Readiness
(OpenBao / RustFS / Model Provider)

S18
Installed Current-Platform Continuity E2E

S20
GB2-CA00 Final As-Built / Golden B v2 Entry Authorization
```

---

# 11. Golden A as Continuity Probe

GB2-CA00에서는 Golden A를 다시 개발하지 않는다.

Golden A는 이미 다음 capability를 한 번에 통과시키는 좋은
**Platform continuity probe**이므로 재사용한다.

```text
live semantic planning
→ COMPILED
→ schedule_next
→ AE worker
→ Approval
→ WC delivery
→ RESUME_EXECUTION
→ NSL Controlled WRITE
→ EOS BusinessOperation
→ EOS outbox
→ AgentResult
→ WORKSPACE_RESULT ACK
→ user-visible result
```

중요한 점은 이번에는:

```text
P8-DEMO process manifest
manual runtime composition
test-side transition
```

없이 **current Platform topology만으로** 이 흐름이 이어져야 한다는 것이다.

---

# 12. Golden Journey Acceptance Rule

Golden Journey acceptance는 다음을 만족해야 한다.

```text
platform_integrated = true
runtime_transition_fixture = false
manual_domain_transition = false
installed_process_continuity = true
```

User/business request 이후 Smoke runner는 다음을 직접 수행할 수 없다.

```text
schedule_next()
AgentExecution state UPDATE
RuntimeJob INSERT
WorkItem / Claim / Assignment creation
Approval persistence
ResultDelivery ACK
WorkResult repository mutation
WA evidence mutation
```

Smoke는 이후:

```text
API/browser call
poll
assert
restart
fault injection
evidence collection
cleanup
```

만 수행한다.

---

# 13. Dependency Lifecycle

외부 dependency는 다음 lifecycle로 분리한다.

```text
Provision
→ Configure
→ Admit
→ Start
→ Ready
→ Run
```

예:

```text
OpenBao
deployment provision
→ runtime secret resolution

RustFS
bucket/IAM/policy provision
→ runtime object-store use

Model Provider
provider capability admission
→ live planning use
```

중요:

```text
configured != ready
```

이다.

---

# 14. Do Not Reopen

GB2-CA00은 기존 architecture를 변경하는 단계가 아니다.

다음은 다시 열지 않는다.

```text
WorkItem != execution authority
Claim = execution authority
CLAIMED_WORKITEM = CA/PA/EA execution trigger
AgentResult alone != success
ResultDelivery ACK required
WC owns WorkItem/Claim/WorkResult
AE owns AgentExecution
EOS owns business transaction
WA = post-work evidence
WA != Scheduler
no cross-service DB
```

---

# 15. Definition of GB2-CA00 Closure

다음 조건을 모두 만족해야 CLOSED로 인정한다.

```text
9 artifacts preserved
20 current processes admitted

AE Agent Runtime worker first-class
WC delivery worker first-class
EOS outbox publisher first-class

generic AE installed runtime factory exists
P8-DEMO uses generic factory
canonical runtime has no Demo dependency

DomainIntentActivatorRegistry exists
Golden A registered as product profile
Capability != Skill preserved

Golden Journey testing contract enforced
runtime transition fixture audit PASS

OpenBao readiness canonical
RustFS readiness canonical
generation provider readiness canonical

P8-DEMO compatibility PASS
current Platform installed continuity PASS
restart/fail-closed acceptance PASS

Repository Full Gate PASS
Statement >= 96%
Branch >= 94%
zero owned residue
git diff --check PASS
```

---

# 16. Golden B v2 Entry Rule

Golden B v2 implementation은 GB2-CA00이 닫힌 후 시작한다.

즉:

```text
GB2-CA00 = CLOSED
        ↓
Golden B v2 implementation = AUTHORIZED
```

그 이후 Golden B v2는 다음에만 집중한다.

```text
manufacturing evidence source
Manufacturing business capability
PA planning profile
manufacturing READ path
Manufacturing Readiness Artifact
IA → WC → PA business journey
WA evidence verification
```

Platform 설치/worker/runtime wiring 문제를 다시 해결하지 않는다.

---

# 17. Recommended Working Order

실제 작업 시에는 다음 순서로 진행한다.

```text
261028_README_GB2_CA00_v1.1.md
        ↓
Source Audit / PAD v1.1
        ↓
GB2-CA00A Consistency Closure v1.0
        ↓
Implementation Slice Plan v1.1
        ↓
S01부터 순차 구현
        ↓
Checkpoint / Full Gate
        ↓
S18 Current Platform E2E
        ↓
S20 Final As-Built
        ↓
Golden B v2
```

---

# 18. Canonical Documents

Required:

```text
1.
261028_GB2_CA00_Platform_Runtime_Internalization_and_
Smoke_to_Product_Promotion_Audit_v1.1.md

2.
261028_GB2_CA00A_Pre_Implementation_Document_
Consistency_Closure_v1.0.md

3.
261028_GB2_CA00_Platform_Runtime_Internalization_
Implementation_Slice_Plan_v1.1.md
```

Optional context:

```text
261028_Golden_B_v2_Manufacturing_Delegation_
Full_Journey_Design_Draft_v0.1.md

P9_Final_AsBuilt_Baseline_and_Next_Phase_Handoff_v1.1.md
```

The optional context does not override the three GB2-CA00 normative working
documents.

---

# 19. Final Position

GB2-CA00 is a **Platform promotion and internalization Gate**.

It is not Golden B business implementation.

Its purpose is to guarantee that when Golden B v2 begins:

```text
User request
→ Platform runtime
→ installed workers
→ business result
```

is a real Platform execution path, not a Smoke-assembled demonstration.

The governing principle remains:

> **Smoke should prove that the Platform works;
> Smoke must not be the thing that makes the Platform work.**
