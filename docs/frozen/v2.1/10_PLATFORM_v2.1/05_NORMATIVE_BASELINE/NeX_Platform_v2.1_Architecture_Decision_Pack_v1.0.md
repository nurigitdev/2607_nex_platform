# NeX Platform v2.1 Architecture Decision Pack v1.0

**상태:** ACCEPTED — FROZEN FOR PLATFORM v2.1 CONTROLLED AMENDMENT  
**목적:** PASS 1~6에서 남은 6개 Open ADR을 결정하여 Platform v2.1 문서 수정의 선행 Architecture Boundary를 고정  
**Authority:**  
1. NeX Agent v2.1 Final Frozen  
2. NSL v0.2 Final Frozen  
3. NeX Agent v2.1 ↔ NSL v0.2 Integration Contract v1.0  
4. NeX Platform v2.0 — Re-baseline Target  

**주의:** 본 ADR은 Platform v2.1 문서/Contract 수정의 normative decision이다. 아직 Platform v2.1 전체 문서 세트가 최종 Frozen되었다는 의미는 아니다.

---

# 1. ADR Summary

| ADR | Decision | Status |
|---|---|---|
| ADR-P21-AGENT-ID-01 | Logical Agent Identity/Profile SoR = **NeX-AE Agent Registry** | ACCEPTED |
| ADR-P21-AGENT-TYPE-01 | WC = **generic AGENT + agent_type discriminator** | ACCEPTED |
| ADR-P21-TENANT-01 | `TenantId` = **explicit first-class identity**, single-tenant도 fixed configured value 사용 | ACCEPTED |
| ADR-P21-PACKAGE-01 | NSP Resolver/Verifier = **AE-API Skill Artifact Gateway**, NSL Runtime 외부 | ACCEPTED |
| ADR-P21-APPROVAL-01 | **WC Human Workflow + EOS Business Approval Hybrid** | ACCEPTED |
| ADR-P21-SCHED-01 | Schedule SoR/Engine = **NeX-WC Recurring Work / Schedule capability** | ACCEPTED |

---

# 2. ADR-P21-AGENT-ID-01
## Persistent Agent / PA Registry Owner

**Status:** ACCEPTED

## Context

Frozen Agent v2.1 defines:

```text
IA / CA / PA / EA
```

and specifically:

```text
PA = Project 1:1 Persistent Logical Agent Identity
```

Platform v2.0 OA owns Employee/Coworker-oriented identity/security data, while AE owns Agent Runtime/Execution.

The Frozen Agent design intentionally left the persistent Agent Registry owner as an Open Decision.

## Decision

> **Persistent Logical Agent Identity/Profile의 authoritative SoR를 NeX-AE-API의 `Agent Registry`로 둔다.**

Canonical separation:

```text
NeX-AE Agent Registry
= logical Agent identity/profile SoR

NeX-OA
= authentication / Principal / RoleBinding / Effective Authority SoR

NeX-AG
= Agent profile governance projection / enable / suspend / kill-switch

NeX-WC
= WorkItem / Assignment / Claim SoR
```

## Agent Registry Candidate Model

```text
AgentIdentity
├─ tenant_id
├─ agent_id
├─ agent_type = IA | CA | PA | EA
├─ profile_ref
├─ status
├─ project_id           # PA mandatory
├─ owner/business refs
├─ created_at
└─ version
```

PA invariant:

```text
one active PA per (tenant_id, project_id)
```

또는 equivalent uniqueness rule을 사용한다.

## Existing OA CoworkerProfile

기존 OA `coworker_profile_ref`는 즉시 삭제하지 않는다.

v2.1에서는:

```text
legacy / employee-bound security profile
```

로 유지하고 AE AgentIdentity와 reference로 연결한다.

다만 이것을 PA/EA까지 포괄하는 generic Agent Registry로 확장하지 않는다.

## Rationale

- PA는 Security Principal 자체가 아니라 **Project-scoped logical execution actor**다.
- OA에 넣으면 Identity/AuthZ와 Agent lifecycle/profile responsibility가 혼합된다.
- AG는 PAP/Governance이므로 Agent Identity SoR가 되면 안 된다.
- WC는 Work SoR이며 Agent Registry가 아니다.
- AE는 Agent lifecycle/runtime의 자연스러운 bounded context다.

## Rejected

### OA owns all Agent Profiles

Rejected because logical Agent lifecycle/profile와 security identity가 결합된다.

### AG owns Agent Registry

Rejected because governance projection이 SoR가 된다.

### WC owns Agent Registry

Rejected because Work coordination과 actor registry가 결합된다.

---

# 3. ADR-P21-AGENT-TYPE-01
## WC Agent Type Encoding

**Status:** ACCEPTED

## Context

Current WC enum:

```text
HUMAN
COWORKER
EXPERT
EXTERNAL_AGENT
SYSTEM
```

Frozen Agent:

```text
IA / CA / PA / EA
```

IA는 user prompt에서 실행되고, CA/PA/EA는 WC Work Claim을 통해 background execution을 시작한다.

## Decision

> **WC actor type은 generic `AGENT`를 사용하고 별도 `agent_type` discriminator로 CA/PA/EA를 표현한다.**

Canonical:

```text
assignee_type:
HUMAN | AGENT | EXTERNAL_AGENT | SYSTEM

agent_type:
CA | PA | EA       # assignee_type=AGENT일 때
```

IA는 기본적으로 WC background claimant가 아니다.

## Routing

기존:

```text
CAPABILITY_POOL
EXPERT_POOL
```

을 migration alias로 유지할 수 있다.

v2.1 canonical routing은:

```text
routing_target_type = CAPABILITY_POOL
eligibility:
  agent_type
  capability
  tenant
  org/project scope
```

를 중심으로 한다.

Project Agent:

```text
agent_type = PA
project_id/project_scope constraint
```

으로 표현한다.

## Rationale

- 신규 Agent Type이 추가될 때 enum 폭증 방지
- WC Work semantics와 Agent taxonomy 분리
- 기존 Pool→Claim model 재사용
- PA/EA를 별도 Work system으로 만들 필요 없음

---

# 4. ADR-P21-TENANT-01
## Initial TenantId Strategy

**Status:** ACCEPTED

## Context

Frozen Agent↔NSL integration requires:

```text
TenantId
!= OrgScope
!= ProjectScope
```

NSL actual IdempotencyKey:

```text
TenantId + BusinessOperationId + WriteNodeId
```

Platform v2.0에는 explicit tenant field가 없다.

현재 초기 배포는 단일 기업 환경일 수 있으나 Architecture는 future multi-tenant 가능성을 막지 않아야 한다.

## Decision

> **`tenant_id`를 Platform v2.1 전 계층의 명시적 first-class identity로 도입한다.**

초기 single-tenant deployment도:

```text
DEFAULT_ENTERPRISE_TENANT_ID
```

와 같은 **설정 기반의 명시적 고정값**을 사용한다.

금지:

```text
TenantId = OrgScope 추론
TenantId = ProjectScope 추론
tenant field 생략
```

## Source / Propagation

Initial authoritative security context source:

```text
Ingress / authenticated context
→ NeX-OA
→ EffectiveAuthorityContext.tenant_id
```

Propagation:

```text
OA
→ AE AgentExecution / SkillExecutionRequest
→ WC WorkItem / Claim
→ CX Security Envelope
→ NSL integration request
→ Audit / Evidence
```

## Tenant Master Registry

v2.1에서는 별도의 복잡한 Tenant Management Product를 만들지 않는다.

Single-tenant phase:

```text
configured platform tenant
```

를 OA security context에 명시한다.

Multi-tenant productization이 필요해지면 Tenant Registry를 별도 ADR로 확장한다.

## Rationale

- NSL idempotency domain과 직접 연결
- Org/Project 변화가 Tenant boundary를 변경하지 않음
- 향후 SaaS/외부 사업화에 migration 가능
- 지금 단일기업 운영에도 구현 부담이 작음

---

# 5. ADR-P21-PACKAGE-01
## NSP Resolver / Verifier Physical Placement

**Status:** ACCEPTED

## Context

Frozen NSL:

```text
Signed NSP
→ Package Verification
→ PackageTrustEvidence
→ VerifiedSkillArtifact
→ NSL Runtime
```

NSL Runtime core는 raw NSO/Manifest signature를 직접 검증하지 않는다.

Platform v2.0 old Runtime은 NSL Runtime 내부에서 SignatureVerifier를 사용한다.

## Decision

> **v2.1 initial physical placement는 NeX-AE-API의 Agent↔NSL Integration Layer 안에 `Skill Artifact Gateway`를 둔다.**

Component:

```text
Skill Artifact Gateway
├─ Exact Skill/Version Resolver
├─ NSP Package Loader
├─ Package Verifier
├─ Runtime Compatibility Check
└─ VerifiedSkillArtifact Builder
```

Flow:

```text
ExecutableStep
→ SkillExecutionRequest
→ Skill Artifact Gateway
→ exact NSP
→ package/signature/hash verification
→ PackageTrustEvidence
→ VerifiedSkillArtifact
→ NSL Runtime
```

## Responsibility Split

```text
AE Skill Artifact Gateway
= runtime resolution / verification orchestration

AG
= publisher/key/package governance, certification, revoke/kill-switch

Artifact Store / Skill Registry
= package storage / version metadata

NSL Runtime
= consume VerifiedSkillArtifact
```

AG가 runtime PackageTrustEvidence를 생성하는 SoR가 되지 않는다.

## Deployment

초기에는 AE-API와 동일 process/service unit에 배치 가능하다.

Logical interface를 유지하면 향후 독립 서비스로 분리 가능하다.

## Rationale

- NSL Runtime core를 Frozen 상태로 유지
- exact Agent plan binding과 가까운 위치에서 artifact resolve
- AG를 hot path로 만들지 않음
- 불필요한 신규 microservice 방지

---

# 6. ADR-P21-APPROVAL-01
## Approval Workflow Placement

**Status:** ACCEPTED

## Context

Current Platform v2.0:

```text
AE Confirmation
EOS Formal Approval
```

Frozen:

```text
Human Confirmation
!= Agent FORMAL_APPROVAL
!= NSL WRITE Approval
!= OA Step-up
```

NSL:

```text
NSL owns WriteIntent / ApprovalRequestId / binding
Platform owns Human Workflow / Decision / Resume scheduling
```

Recent architecture analysis showed WC already owns:

```text
WorkItem
Assignment
Routing
Wait/Event
Timeout
Result
```

and can be extended to human decision work.

## Decision

> **NeX-WC를 Human Work / Approval Workflow Control Plane으로 확장하고, EOS는 Business Formal Approval SoR를 필요한 도메인에서 유지하는 Hybrid 구조를 채택한다.**

### NeX-WC

Owns:

```text
ApprovalWorkItem
Approver routing / assignment
PENDING / APPROVED / REJECTED / EXPIRED
Notification event
Timeout / escalation / delegation
Human decision workflow record
Decision event
```

### Enterprise OS

Owns:

```text
domain business formal approval record
```

when the business domain requires authoritative formal approval.

### NSL

Owns:

```text
WRITE approval semantic identity
WriteIntent
ApprovalRequestId
PayloadHash
WriteIntentHash
Approval evidence binding/validation
```

### OA

Owns:

```text
current approver authorization
```

### AE / IA / AE-WEB

Own:

```text
notification/presentation
Agent WAIT/Resume
```

## Canonical Flow — NSL WRITE

```text
NSL WriteIntent Freeze
→ NSL ApprovalRequest
→ WC ApprovalWorkItem
→ Interactive Agent / AE-WEB Notification
→ Approver
→ OA Authorization
→ WC Decision
→ Approval Decision Event
→ Agent Resume
→ NSL ApprovalEvidence Validation
→ WRITE
```

WC는 NSL binding metadata를 opaque immutable field로 취급한다.

## Canonical Flow — Agent FORMAL_APPROVAL

```text
Agent FORMAL_APPROVAL
→ WC ApprovalWorkItem

if domain business approval required:
  → EOS Approval Adapter / EOS Approval record

decision
→ Agent Resume
```

## SoR Split

```text
Approval workflow / human work state = WC
Business-domain approval transaction = EOS when applicable
NSL WRITE approval binding/evidence = NSL
Authorization = OA
```

## No Separate Approval Service

v2.1에서는 독립 Approval microservice를 만들지 않는다.

추후 다음 조건에서 분리 재검토:

```text
complex multi-stage approval graph
legal e-signature
independent scaling/SLA
cross-platform approval productization
```

---

# 7. ADR-P21-SCHED-01
## Schedule / Recurring Work Bounded Context Owner

**Status:** ACCEPTED

## Context

Platform v2.0:

```text
Schedule = recognized future Work Source
SYSTEM_JOB = scheduler/monitor principal
```

but no ScheduleSpec / Registry exists.

ADR-020:

```text
NeX-WA = Work Asset
WA != Scheduler
```

Frozen Agent:

```text
CA / PA / EA execution starts after successful WC Work Claim
```

Recent Golden Slice Candidate requires persistent daily recurring work.

## Decision

> **NeX-WC를 `Recurring Work / Schedule` capability로 확장하여 ScheduleSpec 및 ScheduleOccurrence의 SoR와 durable time-trigger engine을 담당한다.**

PA may:

```text
create / update / enable / disable
project-owned schedule policy
```

through WC APIs, but:

> **PA process 자체가 timer를 보유하거나 sleep loop를 수행하지 않는다.**

## Canonical Flow

```text
Project / PA
→ WC ScheduleSpec

WC Durable Scheduler
→ ScheduleOccurrence
→ deterministic WorkItem materialization
→ Project-scoped WC WorkItem
→ Eligible PA
→ Atomic Claim
→ CLAIMED_WORKITEM
→ PA AgentExecution
```

## Candidate Contract

```text
ScheduleSpec
├─ tenant_id
├─ schedule_id
├─ owner_ref
├─ project_id
├─ target_work_definition
├─ timezone
├─ cron/calendar
├─ enabled
├─ misfire_policy
├─ concurrency_policy
├─ next_run_at
├─ last_run_at
└─ version

ScheduleOccurrence
├─ occurrence_id
├─ schedule_id
├─ nominal_time
├─ materialized_work_item_ref
└─ state
```

## Misfire Policy

Initial v2.1:

```text
SKIP
CATCH_UP
LATEST_ONLY
```

can reuse the existing Reliability vocabulary, while defining business-schedule semantics separately.

## Idempotency

Occurrence → WorkItem materialization must be deterministic.

Candidate identity:

```text
tenant_id + schedule_id + nominal_occurrence_time
→ occurrence identity
```

Duplicate scheduler execution must not create duplicate WorkItems.

## Why WC

- Schedule occurrence's primary business effect is **WorkItem materialization**
- WC is already Enterprise Work SoR
- WC owns routing/claim/dependency/event
- avoids direct Schedule→AgentExecution contract
- Frozen Agent Claim semantics preserved
- avoids new service and avoids misusing WA

## Rejected

### WA owns Schedule

Rejected by current frozen Platform ADR.

### PA owns timer

Rejected because process lifecycle/HA/restart/scale-out issues and Frozen Trigger contract.

### AE-API direct scheduler

Rejected as initial default because it would create work outside Work SoR and encourages direct PA execution.

### New Scheduler service

Not required at current scale; logical interfaces allow future split.

---

# 8. Dependency Impact

Decisions resolve prior ADR dependencies as follows.

```text
Agent Registry  → AE
WC Agent Type   → generic AGENT + discriminator
Tenant          → explicit OA-originated cross-platform identity
Package         → AE Skill Artifact Gateway
Approval        → WC workflow + EOS domain approval hybrid
Schedule        → WC Recurring Work
```

Resulting core flow:

```text
User / Schedule
        ↓
WC Work / Schedule
        ↓
Claim
        ↓
AE Unified Agent Runtime
        ↓
Agent v2.1
        ↓
Skill Artifact Gateway
        ↓
NSL v0.2
        ↓
Enterprise OS

OA = authority
AG = governance
CX = evidence
MO = model
AE-WEB/IA = interaction
WA = post-work assetization
```

---

# 9. ADR Freeze Rule

These six decisions are:

> **FROZEN FOR PLATFORM v2.1 CONTROLLED AMENDMENT**

Any change requires:

```text
ADR revision
→ impact analysis
→ Unified Change Ledger revision
→ affected docs/contracts amendment
→ consistency re-review
```
