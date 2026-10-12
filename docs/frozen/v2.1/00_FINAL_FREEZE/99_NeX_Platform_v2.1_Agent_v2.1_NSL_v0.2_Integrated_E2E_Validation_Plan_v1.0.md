# NeX Platform v2.1 ↔ NeX Agent v2.1 ↔ NSL v0.2
# Integrated E2E Validation Plan v1.0

**문서 상태:** FINAL VALIDATION PLAN BASELINE  
**작성 목적:** NeX Platform v2.1 Final Consistency Closure 이후, Frozen NeX Agent v2.1 및 Frozen NSL v0.2와의 통합 Architecture/Contract 정합성을 E2E Scenario 기반으로 최종 검증하기 위한 기준 계획 고정  
**기준일:** 2026-09-29  
**중요:** 본 계획은 Architecture/Contract 수준의 Integrated E2E Validation 계획이다. 실제 Source Code Runtime Test/Performance Test와는 구분한다.

---

# 1. Validation Goal

본 Validation의 최종 목표는 다음 세 Frozen/Candidate Architecture가 하나의 실행 체계로 모순 없이 연결되는지 확인하는 것이다.

```text
NeX Platform v2.1
        │
        ▼
NeX Agent v2.1
        │
        ▼
NSL v0.2
        │
        ▼
Enterprise OS / External Systems
```

검증 대상은 단순 API 연결 가능성이 아니다.

다음이 E2E에서 유지되는지 검증한다.

```text
Responsibility / SoR
Identity
Authority
AgentExecution / RuntimeJob
WorkItem / Claim
BusinessOperationId
Approval
NSL Suspension / Resume
Idempotency
Package Trust
Commit / Verification
Reconciliation
Evidence / Audit
Notification
Schedule / Recurring Work
Result Publication
```

---

# 2. Normative Authority

이번 Integrated Validation의 Authority는 다음과 같이 고정한다.

## 2.1 Highest Semantic Authority

```text
AUTH-01  NeX Agent v2.1 Final Frozen
AUTH-02  NSL v0.2 Final Frozen
AUTH-03  NeX Agent v2.1 ↔ NSL v0.2 Integration Contract v1.0
```

## 2.2 Platform Authority

```text
AUTH-04  NeX Platform v2.1 Architecture Decision Pack v1.0
AUTH-05  NeX Platform v2.1 Architecture Consistency Closure & Unified Change Ledger v1.0
AUTH-06  NeX Platform v2.1 Final Consistency Closure Working Set v1.1
```

## 2.3 Conflict Rule

```text
Platform stale Agent assumption
→ Agent v2.1 wins

Platform stale NSL assumption
→ NSL v0.2 wins

Agent↔NSL cross-layer ambiguity
→ Integration Contract v1.0 wins

Platform product placement/ownership
→ Platform v2.1 ADR Pack wins
```

Validation 과정에서 새로운 충돌이 발견되더라도 즉시 문서를 수정하지 않는다.

```text
Issue
→ Root Cause
→ Authority Check
→ Change Ownership
→ ADR / Change Ledger 필요 여부
→ Controlled Amendment
```

---

# 3. Target v2.1 Responsibility Baseline

```text
NeX-AE-WEB
= UI / Workspace / Notification / Human Action Surface

IA
= user-facing Agent actor

NeX-AE-API
= Agent Registry
+ Unified Agent Runtime
+ Agent↔NSL Integration Layer
+ Skill Artifact Gateway

NeX-WC
= Enterprise Work SoR
+ Routing / Assignment / Claim
+ ApprovalWorkItem
+ Recurring Work / Schedule

NeX-OA
= Authentication / Principal / RoleBinding / Tenant
+ Effective Authority Context
+ PDP / Current Authorization

NeX-AG
= PAP / Governance / Kill-switch
+ Agent / EA-Trust / NSP governance

NeX-CX
= Context / Evidence Retrieval
+ EvidenceBundle / CX Evidence Context

NeX-MO
= Model Serving / Deterministic Model Routing

NSL v0.2
= Deterministic Atomic Skill Runtime
+ STRICT WRITE Approval semantics
+ actual WRITE IdempotencyKey
+ Commit / Verification / Write Evidence

Enterprise OS
= Business Transaction SoR
+ Canonical Business API
+ Domain Business Formal Approval SoR where required

NeX-WA
= Work Asset / Post-work Activity / Reporting
NOT Scheduler
```

---

# 4. Validation Principles

## 4.1 No Hidden Ownership Duplication

동일 state/data/action에 대해 두 authoritative owner가 존재해서는 안 된다.

```text
WorkItem              → WC
AgentExecution        → AE
ApprovalWorkItem      → WC
NSL Approval binding  → NSL
Business Transaction  → EOS
Current Authorization → OA
```

## 4.2 Logical Identity Separation

```text
WorkItemId
ClaimId / ClaimGeneration
AgentExecutionId
RuntimeJobId
ExecutableStepId
NSLExecutionId
BusinessOperationId
WriteNodeId
IdempotencyKey
ApprovalWorkItemId
ApprovalRequestId
ScheduleId
ScheduleOccurrenceId
ToolInvocationId
AgentResultId
PublicationOperationId
```

## 4.3 No Silent Retry

```text
Runtime retry != Business WRITE retry
UNKNOWN_COMMIT_STATE → no blind retry
COMMITTED + Verification FAILED → no WRITE retry
```

## 4.4 Approval Separation

```text
Human Confirmation
!= Agent FORMAL_APPROVAL
!= NSL WRITE Approval
!= OA Step-up
```

## 4.5 Trust / Authorization Separation

```text
OA Authorization
!= EA Operation Trust
!= NSL Package Trust
!= Human Approval
```

어느 하나의 ALLOW도 다른 required control의 DENY를 override할 수 없다.

## 4.6 Context Boundary

```text
CX Evidence Context != AgentContext != NSL runtime_context
```

Canonical flow:

```text
CX Evidence Context
→ Agent Context Builder
→ AgentContext
→ Compiler-bound typed inputs / explicit refs
→ NSL
```

---

# 5. Validation Structure

Integrated E2E Validation은 6 Pass로 수행한다.

```text
PASS E1 — Authority / Identity Chain
PASS E2 — Interactive User-driven Execution
PASS E3 — Work / Delegation / Approval / Resume
PASS E4 — Business WRITE / Commit / Reconciliation
PASS E5 — Governance / Evidence / Notification / Publication
PASS E6 — Scheduled / Recurring Project Agent Execution
```

---

# 6. PASS E1 — Authority / Identity Chain

검증 체인:

```text
TenantId
→ Authenticated Principal
→ Business Actor
→ RoleBinding
→ Org / Project Scope
→ AgentIdentity
→ WorkItem / Claim
→ AgentExecution
→ BusinessOperationId
→ NSLExecutionId
```

검증 항목:

```text
E1-G01 TenantId explicit
E1-G02 TenantId != OrgScope != ProjectScope
E1-G03 Principal != Business Actor
E1-G04 AgentIdentity SoR = AE Agent Registry
E1-G05 WorkItem/Claim SoR = WC
E1-G06 Current authorization SoR = OA
E1-G07 Background Agent starts only after successful Claim
E1-G08 PA project 1:1 logical identity preserved
```

---

# 7. E2E Scenario Catalog

이번 최종 Validation은 **12개 Core Scenario + Fault Variants**를 사용한다.

---

# 8. E2E-01 — User → IA → READ Skill → Result

```text
User
→ AE-WEB
→ AE-API
→ IA PROMPT
→ AgentExecution
→ Intent Resolution
→ CX Evidence Retrieval
→ Agent Context Builder
→ AgentPlan
→ Compiler
→ LOCAL_SKILL
→ Skill Artifact Gateway
→ VerifiedSkillArtifact
→ NSL READ
→ StepResult
→ AgentResult
→ AE-WEB
```

검증:
- AE-WEB != IA
- CX Evidence Context != AgentContext
- exact skill/version resolution
- READ has no WRITE Approval
- current OA permission-aware retrieval
- Result/Evidence refs preserved

---

# 9. E2E-02 — Golden A: Voucher Draft WRITE with NSL Approval

```text
User
→ IA
→ Plan / Compile
→ optional Human Confirmation
→ LOCAL_SKILL NEW
→ NSL CHECK
→ WriteIntent Freeze
→ ApprovalRequestId
→ WAITING_FOR_APPROVAL
→ WC ApprovalWorkItem
→ Notification
→ Approver
→ OA current authorization
→ APPROVAL_DECIDED
→ Agent Resume
→ NSL RESUME
→ ApprovalEvidence Validation
→ runtime-derived IdempotencyKey
→ durable WRITE_REQUESTED
→ EOS Canonical WRITE
→ CommitState
→ VerificationStatus
→ Agent Completion Verification
→ Result Publication
```

핵심:
- Human Confirmation != NSL WRITE Approval
- NSL owns ApprovalRequestId
- WC owns human workflow
- OA authorizes approver
- EOS owns business transaction
- Agent owns Resume
- NSL owns actual WRITE key

---

# 10. E2E-03 — Agent FORMAL_APPROVAL + NSL WRITE Approval

Expected:

```text
2 distinct approval domains
2 distinct identities
No proof substitution
```

EOS Business Formal Approval이 필요한 domain이면:

```text
WC ApprovalWorkItem
→ EOS Business Approval Adapter
```

를 별도 유지.

---

# 11. E2E-04 — CA Delegation through WC

```text
Parent Agent
→ DELEGATE_WORK
→ WC WorkItem
→ Capability Pool
→ Atomic Claim
→ CA Assignment
→ CLAIMED_WORKITEM
→ Child AgentExecution
→ Result
→ WC WorkResult
→ Parent Resume
```

검증:
- WorkItem != AgentExecution
- Routing != Assignment
- Claim determines actual assignee
- Parent waits for WorkResult, not Claim

---

# 12. E2E-05 — PA Project Work Execution

```text
Project
→ AE Agent Registry PA
→ Project-scoped WC WorkItem
→ PA eligibility
→ Atomic Claim
→ PA AgentExecution
→ project Context / CX
→ plan / skill / result
```

검증:
- one active PA per project
- PA authority = project bounded
- no member permission union
- PA != Enterprise Project SoR

---

# 13. E2E-06 — EA-Trust ALLOW + OA DENY

Expected:

```text
OA DENY
→ Protected Action BLOCK
→ NSL WRITE = 0
```

Fault Variant:

```text
OA ALLOW
Trust fingerprint != actual WriteCallRequest
→ GovernedWriteExecutionPort BLOCK
→ WRITE=0
```

---

# 14. E2E-07 — Package Trust Failure

```text
Agent plan valid
OA ALLOW
exact skill/version selected
→ Skill Artifact Gateway
→ Signed NSP invalid/missing/revoked
```

Expected:

```text
VerifiedSkillArtifact creation fail
NSL execution blocked
Provider WRITE=0
```

---

# 15. E2E-08 — Duplicate RuntimeJob / Idempotency

```text
same semantic operation
→ duplicate RuntimeJob / retry
→ same BusinessOperationId
→ NSL derives same IdempotencyKey
```

Expected:

```text
same key + same payload
→ one business effect

same key + different PayloadHash
→ IDEMPOTENCY_CONFLICT
```

---

# 16. E2E-09 — UNKNOWN_COMMIT_STATE → Reconciliation

```text
WRITE_REQUESTED
→ EOS/provider ambiguity
→ UNKNOWN_COMMIT_STATE
→ RECONCILIATION_REQUIRED
→ Agent/Platform Reconcile Job
→ authoritative EOS query
```

검증:
- no blind retry
- BusinessOperationId stable
- NSL evidence preserved
- EOS remains Business SoR

---

# 17. E2E-10 — COMMITTED + Verification FAILED

Expected:

```text
CommitState = COMMITTED
VerificationStatus = FAILED
WRITE retry = 0
AgentResult may be FAILED/PARTIAL/CONFLICT
```

---

# 18. E2E-11 — Result Publication Failure

```text
Business WRITE COMMITTED
→ AgentResult
→ Email / Workspace / Notification publication
→ ACK lost / unknown delivery
```

Expected:

```text
Publication-specific retry/reconcile
Business WRITE count remains 1
```

---

# 19. E2E-12 — Scheduled PA Recurring Work

```text
PA / Project
→ WC ScheduleSpec
→ WC Durable Scheduler
→ ScheduleOccurrence
→ project-scoped WorkItem
→ Eligible PA
→ Atomic Claim
→ CLAIMED_WORKITEM
→ PA AgentExecution
→ Result
→ WA post-work projection
```

검증:
- WA != Scheduler
- PA has no in-process timer
- Schedule does not directly start AgentExecution
- Occurrence does not duplicate WorkItem
- Misfire policy deterministic

---

# 20. Fault Variant Catalog

## FV-01 Unauthorized Approver
OA DENY → Decision persistence denied → Resume=0

## FV-02 Approval Replay / Hash Mismatch
ApprovalRequestId / BusinessOperationId / PayloadHash / WriteIntentHash mismatch → WRITE=0

## FV-03 Package Revoked after Plan
Execution-time package governance/trust check → BLOCK

## FV-04 Kill-switch after WAIT
Resume preflight → BLOCK

## FV-05 Duplicate Approval Decision Event
One active wait → one Resume Job

## FV-06 Duplicate Schedule Scanner
One nominal occurrence → one ScheduleOccurrence → one WorkItem

## FV-07 Schedule Misfire
SKIP / CATCH_UP / LATEST_ONLY deterministic

## FV-08 Tenant Mismatch
Cross-tenant reference → fail closed

## FV-09 CX Authority Changed
Old evidence context does not override current OA/execute authorization

## FV-10 Publication ACK Lost
Publication retry only; Business WRITE count remains 1

---

# 21. Product Coverage Matrix

| Product | Must be exercised by |
|---|---|
| AE-WEB | E2E-01, 02, 03, 11 |
| AE-API | All Agent scenarios |
| WC | 02, 03, 04, 05, 12 |
| OA | 01, 02, 03, 05, 06, 12 |
| AG | 06, 07, kill-switch variants |
| CX | 01, 05, Evidence variants |
| MO | 01, 05 |
| NSL | 01, 02, 03, 06~10 |
| EOS | 02, 03, 09, 10 |
| WA | 12 post-work projection |

---

# 22. Identity Trace Matrix

가능한 범위에서 다음 chain을 연결한다.

```text
tenant_id
correlation_id
WorkItemId
ClaimId
AgentExecutionId
RuntimeJobId
ExecutableStepId
NSLExecutionId
BusinessOperationId
ApprovalWorkItemId
ApprovalRequestId
ScheduleId / OccurrenceId
WriteNodeId
ToolInvocationId
BusinessReference
StepResultId
AgentResultId
PublicationOperationId
```

---

# 23. Evidence / Audit Validation

Canonical ownership:

```text
NSL detailed execution/write evidence → NSL
Agent runtime / Step / Result          → AE
Work / Claim / Approval / Schedule    → WC
Authorization                          → OA
Governance                             → AG
Evidence Retrieval                     → CX
Business Transaction                  → EOS
Post-work Activity/Asset              → WA
```

Integrated Audit은 stable ref/hash/correlation/semantic summary로 연결한다.

---

# 24. Validation Result Classification

## PASS
현재 Frozen/Closure contract만으로 모순 없이 Scenario가 완료됨.

## CONDITIONAL PASS
Architecture는 compatible하지만 exact Contract/Field가 비어 있음.

## FAIL
현재 contract 그대로 구현하면 ownership/security/retry/resume/idempotency 문제가 발생함.

---

# 25. Issue Classification

```text
E2E-P0  = Freeze blocker / safety / ownership contradiction
E2E-P1  = Interface / schema / naming mismatch
E2E-PCG = Platform Contract Gap
E2E-P2  = Editorial / reference hygiene
```

---

# 26. Final Freeze Gate

```text
F-G01 E2E Core 12 Scenario PASS
F-G02 Required Fault Variants PASS
F-G03 E2E-P0 = 0
F-G04 E2E-P1 = 0
F-G05 E2E-PCG = 0
F-G06 Platform document consistency remains CLOSED
F-G07 Agent v2.1 Frozen semantics unchanged
F-G08 NSL v0.2 Frozen semantics unchanged
F-G09 SoR ownership matrix has no dual owner
F-G10 Identity chain traceable
F-G11 Approval domains remain separated
F-G12 no blind WRITE retry
F-G13 package/governance/current-policy controls fail closed
F-G14 Schedule→WorkItem→Claim→Agent contract PASS
F-G15 WA remains post-work assetization only
```

Final state:

> **NeX Platform v2.1 ↔ NeX Agent v2.1 ↔ NSL v0.2 INTEGRATED E2E CONSISTENCY — CLOSED / FROZEN**

---

# 27. Deliverables

```text
1. Integrated E2E Validation Report v1.0
2. Scenario-by-Scenario Validation Matrix
3. Fault Variant Validation Matrix
4. E2E Identity / SoR Trace Matrix
5. Final Remaining Issue Register
6. Final Freeze Declaration
```

---

# 28. Execution Order

```text
Step 1  PASS E1 — Identity / Authority

Step 2
E2E-01 READ
E2E-04 CA Delegation
E2E-05 PA Project Work

Step 3
E2E-02 Golden A WRITE
E2E-03 Dual Approval
E2E-06 Trust/OA
E2E-07 Package Trust

Step 4
E2E-08 Idempotency
E2E-09 Unknown Commit
E2E-10 Verification Failure

Step 5
E2E-11 Publication Failure

Step 6
E2E-12 Scheduled PA Recurring Work

Step 7
Fault Variants FV-01 ~ FV-10

Step 8
Issue Consolidation / Independent Re-check

Step 9
Final Freeze Decision
```

---

# 29. Golden Scenario Taxonomy Note

기존 Platform v2.0 taxonomy:

```text
Golden A = Accounting
Golden B = Collaboration
Golden C = WorkAsset / Labor
```

은 historical naming으로 유지한다.

해외입찰 자동 모니터링은:

> **Golden Slice Candidate — Overseas Business Monitoring**

으로 별도 유지한다.

E2E-12 Schedule/PA Scenario가 PASS한 뒤 기존 Golden C 유지 / Golden D 추가 / taxonomy 재편 여부를 별도 결정한다.

---

# 30. Plan Freeze Statement

> **Integrated E2E Validation Plan v1.0 — FROZEN FOR FINAL VALIDATION**

이후 Scenario 추가/삭제 또는 Final Freeze Gate 변경은 본 계획의 revision으로 관리한다.
