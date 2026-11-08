# NSL v0.2 Controlled Write / Approval / Idempotency Detailed Design v0.1

**문서 버전:** v0.1  
**상태:** Cross-Cutting Architecture Baseline — Closure Aligned  
**작성일:** 2026-08-23  
**대상:** NSL Language v0.2 / Runtime / Compiler / Tool Contract  
**기본 Profile:** `NSL-0.2-STRICT`  
**Architecture Closure 기준:** `NSL v0.2 Architecture Consistency Closure and Unified Change Ledger v1.0 — FROZEN`

---

# 1. 목적

본 문서는 NSL v0.2에서 처음 도입되는 Side Effect 기능을 안전하게 실행하기 위한 **Cross-Cutting Semantic Architecture**를 정의한다.

본 문서는 Approval UI, Queue, Retry Scheduler와 같은 Control Plane 구현을 NSL 내부에 포함시키는 문서가 아니다. NSL은 Deterministic Skill Execution Plane으로서 WRITE의 정적/동적 안전 조건, Approval Evidence, Idempotency, Commit/Verification 의미론을 정의한다.

핵심 기능:

```text
WRITE
APPROVE
Suspend / Resume Semantics
BusinessOperationId
ApprovalRequestId
IdempotencyKey / PayloadHash
Commit State
Post-Write Verification
Write Audit / Evidence
Verified Signed NSP Trust
Risk Classification + External Policy Decision
```

문서 Authority 관점에서 본 문서는 Frozen Architecture Decision과 함께 **Cross-cutting Semantic Architecture**를 담당하며, SRS는 normative requirements, 이후 IR/Tool/Compiler/Runtime 문서는 component-level execution design을 담당한다.

---

# 2. v0.1과 v0.2의 차이

v0.1:

```text
READ
→ CALCULATE
→ CHECK
→ EMIT
```

v0.2:

```text
READ
→ DERIVE
→ CHECK
→ WRITE ELIGIBILITY
→ APPROVE
→ WRITE
→ VERIFY
→ EMIT
```

v0.2에서는 업무 시스템의 상태가 변경되므로, 기존 Validation 성공만으로 실행 허용 여부를 판단해서는 안 된다.

---

# 3. 핵심 설계 원칙

1. LLM은 NSL Runtime 내부에서 호출하지 않는다.
2. 자연어 Intent와 후보 파라미터 결정은 NeX-AE가 담당한다.
3. NSL은 최종 파라미터와 업무 규칙을 Deterministic하게 검증한다.
4. WRITE는 Canonical Business Tool을 통해서만 수행한다.
5. Raw SQL / arbitrary HTTP / direct DB Write는 금지한다.
6. WRITE 전에는 명시적 Approval이 필요하며, `NSL-0.2-STRICT`에서는 **Approval↔WRITE를 exactly 1:1**로 연결한다.
7. Approval은 Write Intent Hash에 Binding된다.
8. 동일 업무 WRITE는 Suspend/Resume/Re-execution/Reconciliation 동안 유지되는 **BusinessOperationId**를 가져야 한다.
9. `IdempotencyKey`와 `PayloadHash`는 분리하며 WRITE는 Idempotent해야 한다.
10. Commit 여부가 불확실하면 NSL Runtime은 자동 Retry하지 않는다.
11. 실제 Database Transaction과 durable idempotency 보장은 Canonical Business API가 책임진다.
12. v0.2 Strict에서는 Skill당 1개의 WRITE만 허용한다.
13. WRITE는 FOREACH 내부에서 금지한다.
14. Risk Level은 Tool/Skill의 classification metadata이며, User/Tenant별 allow/deny 판단은 외부 Policy/OA가 담당한다.
15. Approval routing/UI/notification/persistence, Resume scheduling, Retry/Reconciliation decision은 Agent/Platform Control Plane이 담당한다.
16. Production WRITE trust는 기존 **Signed NSP → Verified Package** 경계를 재사용한다.
17. Approval TTL만으로 freshness를 보장하지 않으며 WRITE 시점의 Business Preconditions를 Canonical Business API가 재검증해야 한다.

---

# 4. 계정과목 600개 문제의 위치

NSL v0.2는 계정과목 검색용 AI Language를 만들지 않는다.

```text
사용자:
"부산 고객사 방문 KTX 84,000원 전표 등록"

        ↓

NeX-AE
Intent / Entity Extraction

        ↓

ACCOUNT.SEARCH_ACCOUNT_CODES
Top 20 / Full Account Master

        ↓

후보 Ranking
예: 여비교통비

        ↓

NSL Input
account_code
project_code
amount
description

        ↓

NSL Validation
```

NSL은 선택된 계정코드가 유효한지 다시 확인한다.

---

# 5. Source Syntax Baseline

```nsl
approve VOUCHER_CREATE {
    message "다음 내용으로 전표 Draft를 등록하시겠습니까?";
}

let voucher =
    write FINANCE.CREATE_VOUCHER_DRAFT(
        account_code = account_code,
        project_code = project_code,
        amount = amount,
        description = description
    )
    approved_by VOUCHER_CREATE;
```

새 Keyword:

```text
write
approve
approved_by
```

---

# 6. WRITE Scope

v0.2 언어 수준에서 WRITE는 Side Effect Tool Invocation을 의미한다.

허용 대상:

```text
CREATE
CREATE_DRAFT
```

초기 제외:

```text
UPDATE
DELETE
CANCEL
POST / FINALIZE
```

Tool Contract가 `operation_kind`를 선언한다.

---

# 7. Static WRITE Safety

Compiler는 다음을 검증한다.

```text
WRITE Tool is declared in requires
Tool Capability == WRITE
Operation Kind supported by NSL 0.2
Approval Ref exists
Approval Ref occurs before WRITE
Approval ↔ WRITE exactly 1:1
Unused Approval 없음
One WRITE maximum per Skill
WRITE not inside FOREACH
All Write Arguments statically typed
Risk metadata exists
Tool Contract declares idempotency
Tool Contract declares atomicity
No dynamic WRITE tool
```

이 제한은 일반 Compiler Option으로 임의 완화하지 않고 `NSL-0.2-STRICT` Semantics Profile의 Safety Invariant로 유지한다.

---

# 8. Write Eligibility

Validation 결과와 실제 WRITE 실행 허용 상태를 분리한다.

```text
CheckStatus:
PASS / FAIL / UNKNOWN

PreWriteEligibility:
ALLOWED
BLOCKED
REQUIRES_APPROVAL
```

기본 Rule:

```text
Any required CHECK == FAIL
→ BLOCKED

Any required CHECK == UNKNOWN
→ BLOCKED

Checks all PASS + approval missing/pending
→ REQUIRES_APPROVAL

Checks all PASS
+ Approval Evidence valid
+ current Policy Decision allow
+ Runtime/Tool Preconditions pass
→ ALLOWED
```

`RECONCILIATION_REQUIRED`는 WRITE 이전 Eligibility가 아니다.

```text
UNKNOWN_COMMIT_STATE
→ ExecutionStatus / Disposition = RECONCILIATION_REQUIRED
```

즉 `PreWriteEligibility`, `CommitState`, `ExecutionStatus/Disposition`을 서로 다른 lifecycle layer로 유지한다.

---

# 9. Approval Request

Approval Request는 단순 메시지가 아니라 **특정 Business Operation의 실행 instance에 Binding된 승인 요청**이다.

정적 Source ID와 실행 instance ID를 구분한다.

```text
ApprovalId
= Source / IR에 선언된 정적 Approval ID

ApprovalRequestId
= 이번 BusinessOperation에서 생성된 실제 승인 요청 instance ID
```

필수 정보:

```text
tenant_id / principal reference
business_operation_id
approval_request_id

skill_id / version
skill_semantic_hash

approval_id
write_node_id
tool_id

payload_hash
write_intent_hash

risk_level
requested_by
requested_at
expires_at(optional)

display_safe_summary
protected_payload_ref
data_classification
message
```

Raw normalized WRITE payload를 Approval Event/Queue/Audit에 반복 복제하지 않는다. 상세 Payload가 필요한 경우 권한이 확인된 경로를 통해 Protected Snapshot/Checkpoint를 조회한다.

---

# 10. Write Intent Hash

Approval은 실제 WRITE 내용과 Binding되어야 한다.

먼저 Canonical Arguments에서 Payload Hash를 계산한다.

```text
payload_hash =
HASH(canonical_write_arguments)
```

Write Intent Hash는 실행 의미와 Payload Identity를 결합한다.

```text
write_intent_hash =
HASH(
    skill_semantic_hash
    + write_node_id
    + tool_id
    + payload_hash
)
```

Approval Evidence는 별도로 다음 실행 identity와 결합되어야 한다.

```text
business_operation_id
approval_request_id
approval_id
skill_semantic_hash
write_intent_hash
decision / expiration / integrity evidence
```

Resume 시 재계산한 `payload_hash` 및 `write_intent_hash`가 Approval Evidence와 다르면 WRITE를 금지한다.

Payload 자체가 변경되어야 한다면 기존 Approval을 재사용하지 않고 새로운 WriteIntent와 ApprovalRequest를 생성해야 한다.

---

# 11. Suspend / Resume

Approval 시 Runtime Worker가 Block된 채 기다리지 않는다.

Approval request publish와 Checkpoint persistence 사이의 crash inconsistency를 방지하기 위해 순서를 고정한다.

```text
NSL Runtime
RUNNING
  ↓
APPROVE
  ↓
WriteIntent Freeze
  ↓
ApprovalRequestId 생성
  ↓
Checkpoint Persist (durable)
  ↓
Approval Request Publish (idempotent)
  ↓
WAITING_FOR_APPROVAL
  ↓
Worker 종료

---------------- Agent / Platform Control Plane ----------------
Approval Routing / UI / Notification
  ↓
Human Decision
  ↓
Resume Job Scheduling / Enqueue

---------------- NSL Resume Boundary ----------------
Worker
  ↓
Checkpoint Restore
  ↓
Approval Evidence / Integrity 검증
  ↓
BusinessOperationId / ApprovalRequestId Binding 검증
  ↓
Write Intent / Payload Hash 검증
  ↓
Current Policy / Preconditions 검증
  ↓
WRITE
```

`RESUME_QUEUED`는 NSL Runtime의 durable ExecutionStatus가 아니라 Agent/Platform Queue State다.

NSL은 Approval workflow를 orchestrate하지 않고 ApprovalRequest / ApprovalEvidence 의미론과 Suspend/Resume execution semantics만 담당한다.

---

# 12. Execution Checkpoint

Checkpoint에는 최소 다음을 저장한다.

```text
execution_id
business_operation_id

skill semantic hash
runtime version
IR version

frame/symbol values needed after resume
check results

approval_id
approval_request_id
write intent hash
payload hash
protected payload / snapshot reference

resource usage
tool snapshots used before approval
trace sequence

policy / trust evidence references as required
```

민감정보는 tenant isolation, encryption at rest, access control, retention, redaction 정책을 적용한다.

Checkpoint는 Approval Request를 외부에 publish하기 전에 durable하게 저장되어야 한다.

---

# 13. Approval Token

Approval 성공 후 NeX-AE/Approval Service는 Runtime에 **Approval Evidence**를 전달한다.

권장 정보:

```text
tenant_id
business_operation_id
approval_request_id

approval_id
skill_semantic_hash

decision = APPROVED / REJECTED
approver_id
decided_at
expires_at(optional)

write_intent_hash
approval_version
signature / integrity token
```

`ApprovalId`는 Source/IR의 정적 ID이고 `ApprovalRequestId`는 실제 승인 요청 instance ID다.

Approval이 REJECTED이면 WRITE하지 않는다. REJECTED를 Runtime technical failure로 오인하지 않고 명시적인 Business Outcome으로 종료할 수 있다.

Approval Evidence가 다른 BusinessOperationId/ApprovalRequestId에 재사용되거나 Intent Hash가 다르면 무효다.

---

# 14. Approval Expiration

Approval과 실제 실행 사이의 시간이 지나치게 길면 External State가 바뀔 수 있다.

Tool/Skill Policy에서:

```text
approval_ttl
```

을 둘 수 있다.

TTL 초과:

```text
APPROVAL_EXPIRED
→ WRITE 금지
→ 재승인 필요
```

단, **Approval TTL은 freshness를 완전히 보장하지 않는다.**

예를 들어 승인 대기 중 회계기간이 닫히거나 프로젝트가 비활성화될 수 있다. 따라서 WRITE 시점에는 Canonical Business API가 다음 중 하나 이상의 방식으로 Business Preconditions를 재검증해야 한다.

```text
optimistic version / revision
ETag / precondition token
transactional business revalidation
equivalent provider-side precondition
```

Business Preconditions 실패 시 기존 Approval을 근거로 WRITE를 강행해서는 안 된다.

---

# 15. Idempotency Key

Runtime은 Logical Business WRITE마다 Idempotency Key를 생성한다.

동일한 업무 WRITE의 identity는 `execution_id`가 아니라 **BusinessOperationId**가 기준이다.

권장 Logical Model:

```text
IdempotencyKey =
HASH(
    tenant_id
    + business_operation_id
    + write_node_id
)

PayloadHash =
HASH(canonical_write_arguments)
```

예:

```text
idem:8a7f...
payload:sha256:...
```

`IdempotencyKey`와 `PayloadHash`는 분리하여 Tool Layer에 전달한다.

Suspend/Resume, Runtime re-execution, Reconciliation 과정에서 동일 BusinessOperationId / WriteNodeId라면 동일 Idempotency Key를 재사용해야 한다.

---

# 16. Idempotency Contract

WRITE Tool Contract는 다음을 선언해야 한다.

```text
idempotency.required = true
idempotency.scope
idempotency.retention
duplicate_behavior
payload_conflict_behavior
```

동일 Key + 동일 PayloadHash:

```text
→ 동일 Business Object Reference / Original Result 반환
```

동일 Key + 다른 PayloadHash:

```text
→ IDEMPOTENCY_CONFLICT
```

Durable duplicate guarantee는 Canonical Business API가 책임지며 NSL Runtime은 stable key와 payload identity를 전달하고 결과를 보존한다.

---

# 17. Atomicity

NSL Source는 전표 Header/Line 등을 여러 WRITE로 조립하지 않는다.

금지 예:

```text
CREATE_HEADER
CREATE_DEBIT_LINE
CREATE_CREDIT_LINE
```

권장:

```text
FINANCE.CREATE_VOUCHER_DRAFT
```

Canonical Business API가 내부 Transaction을 책임진다.

Tool Contract:

```text
atomicity = ATOMIC
```

을 v0.2 WRITE의 기본 요구사항으로 한다.

---

# 18. Commit State

```text
COMMITTED
NOT_COMMITTED
UNKNOWN_COMMIT_STATE
```

Tool transport success/failure와 CommitState를 혼합하지 않는다.

예:

```text
Provider network timeout after upstream commit
→ UNKNOWN_COMMIT_STATE
```

NSL Runtime은 `UNKNOWN_COMMIT_STATE`에서 자동 Retry하지 않는다.

WRITE Retry 가능 여부는 명령이 아니라 `RetrySafety` evidence로 표현한다.

```text
CommitState = NOT_COMMITTED
+ idempotency supported
+ Tool Contract retry-safe
→ SAFE_TO_RETRY evidence 가능
```

실제 Retry 여부와 시점은 Agent/Platform Control Plane이 결정한다.

---

# 19. Reconciliation

`UNKNOWN_COMMIT_STATE` 발생 시:

```text
CommitState
→ UNKNOWN_COMMIT_STATE

ExecutionStatus / Disposition
→ RECONCILIATION_REQUIRED
```

NSL Runtime은 다음과 같은 structured evidence를 반환한다.

```text
business_operation_id
idempotency_key
payload_hash
write_intent_hash
tool_id
provider_transaction_id(optional)
business_reference(optional)
verification_hint
failure / timeout evidence
```

가능한 reconciliation action 예시는:

```text
business_key 조회
idempotency query
verification tool
operator review
compensation / manual decision
```

이지만, **어떤 action을 선택하고 실행할지는 Agent/Platform Control Plane의 책임**이다.

확정 전에는 동일 업무를 새 Idempotency Key로 재실행하지 않는다.

---

# 20. Post-Write Verification

WRITE 후 생성된 Business Object가 실제 존재하는지 검증한다.

방법:

```text
Write Response Reference
+
Verification READ Tool
```

예:

```text
FINANCE.CREATE_VOUCHER_DRAFT
→ voucher_no

FINANCE.GET_VOUCHER
(voucher_no)
→ verify
```

Verification 실패 시 Commit 자체가 실패했다는 의미는 아니다.

별도 상태로 관리한다.

---

# 21. WRITE Tool Result

권장 구조:

```text
WriteResultEnvelope
├─ business_operation_id
├─ value
├─ business_reference
├─ commit_state
├─ idempotency_key
├─ payload_hash
├─ approval_request_id
├─ write_intent_hash
├─ provider_transaction_id
├─ committed_at
├─ verification_hint
└─ metadata
```

CommitState와 VerificationStatus는 별도로 유지한다.

```text
commit_state = COMMITTED
verification_status = FAILED
```

인 경우에도 Commit을 NOT_COMMITTED로 재분류하거나 자동 WRITE를 재실행하지 않는다.

---

# 22. Risk

권장 기본 Risk Classification:

```text
R0 pure calculation
R1 ordinary read
R2 sensitive read
R3 draft write
R4 business write
R5 financial/final/external transaction
```

v0.2 초기 Acceptance는 R3 중심을 권장한다.

Risk Level은 Tool/Skill의 **static classification metadata**다.

다음은 외부 Policy/OA가 결정한다.

```text
이 Tenant에서 R3/R4를 허용하는가?
이 Principal이 해당 WRITE를 수행할 수 있는가?
MFA / 추가 승인 조건이 필요한가?
```

NSL Compiler는 Risk metadata의 존재/형식만 검증하고, Runtime은 WRITE 직전에 현재의 `PolicyDecision` 또는 검증 가능한 Policy Evidence를 확인한다.

---

# 23. Signed NSP Trust Boundary

Production WRITE의 Authenticity는 별도의 중복 `.nso` Signature 체계를 기본으로 만들지 않고, v0.1에서 검증된 **Signed NSP Package Trust Boundary**를 재사용한다.

```text
Canonical NSO / Skill Artifact
        ↓
NSP Build
        ↓
Package Hash / Publisher Signature
        ↓
NspVerifier / Trusted Key
        ↓
Verified Package / Verified Skill Artifact
        ↓
Runtime Preflight
```

Production WRITE는 다음을 만족해야 한다.

```text
Canonical IR Valid
Semantic Hash Valid
Package Integrity Valid
Package Signature Valid
Signing Key Trusted
Skill Version / Feature Allowed
```

Runtime은 raw `SkillObject`에 대해 별도의 독립 SignatureVerifier 경로를 중복 구축하기보다 Verified Package Trust Evidence를 소비한다.

READ-only Skill의 development trust policy는 별도로 둘 수 있으나 Production WRITE는 trusted verified package가 필수다.

---

# 24. Replay Safety

Replay는 실제 Side Effect를 재실행하지 않는다.

```text
Replay Tool/Write Executor
→ recorded Tool / Write Outcome

WRITE node
→ recorded Commit Outcome
```

v0.2 Replay에서는 WRITE뿐 아니라 실행 결과에 영향을 주는 Control Evidence도 Snapshot으로 재사용한다.

```text
Approval Evidence Snapshot
Policy Decision Snapshot
Verified Package / Trust Evidence
Write Outcome Snapshot
Verification Outcome Snapshot
```

Replay 시 현재 Approval Service나 Policy Service를 다시 호출하여 과거 실행 의미를 바꾸지 않는다.

> Replay = **no live control-plane decision calls + no live WRITE**

실제 ERP/Business Provider 호출은 금지한다.

---

# 25. Audit

WRITE 관련 필수 Audit Event:

```text
WRITE_INTENT_CREATED
APPROVAL_REQUESTED
EXECUTION_SUSPENDED
APPROVAL_APPROVED
APPROVAL_REJECTED
EXECUTION_RESUMED
WRITE_REQUESTED
WRITE_COMMIT_CONFIRMED
WRITE_COMMIT_UNKNOWN
WRITE_VERIFIED
WRITE_VERIFICATION_FAILED
EXECUTION_RECONCILIATION_REQUIRED
```

Audit/Event에는 가능한 범위에서 다음 identity/evidence를 연결한다.

```text
execution_id
business_operation_id
approval_request_id
node_id
skill semantic hash
idempotency_key
payload_hash
write_intent_hash
```

Raw WRITE Payload를 generic Audit Event에 직접 반복 저장하지 않는다. 필요한 경우 protected snapshot/reference와 data classification을 기록한다.

---

# 26. v0.2 Failure Safety Invariants

```text
WRT-01 FAIL → no WRITE
WRT-02 UNKNOWN → no WRITE
WRT-03 No valid Approval Evidence → no WRITE
WRT-04 Approval Intent/Payload Hash Mismatch → no WRITE
WRT-05 Untrusted/Invalid Signed NSP Package → no Production WRITE
WRT-06 Tool Contract Hash Mismatch → no WRITE
WRT-07 Same Idempotency Key + Different PayloadHash → IDEMPOTENCY_CONFLICT
WRT-08 UNKNOWN_COMMIT_STATE → no automatic retry
WRT-09 Replay → no live Control decision / no live WRITE
WRT-10 WRITE inside FOREACH → compile error
WRT-11 More than one WRITE → compile error
WRT-12 Non-atomic WRITE Tool → compile/preflight reject
WRT-13 Approval↔WRITE mapping must be exactly 1:1 in NSL-0.2-STRICT
WRT-14 Checkpoint must be durable before Approval Request publish
WRT-15 Write-time Business Preconditions must be satisfied before provider WRITE
```

Retry/Reconciliation execution policy는 Agent/Platform Control Plane이 담당하며 NSL은 안전한 evidence와 상태를 반환한다.

---

# 26.1 Canonical Control / Execution Boundary

```text
Agent / Platform Control Plane
  Intent / Parameters
  BusinessOperationId
  Approval Routing / UI / Decision
  Policy Decision
  Resume Scheduling
  Retry / Reconciliation Decision
            │
            ▼
NSL Deterministic Execution Plane
  READ / CHECK
  PreWriteEligibility
  WriteIntent / PayloadHash
  ApprovalRequest / Checkpoint
  ApprovalEvidence Validation
  WriteGuard
  IdempotencyKey
  Atomic WRITE Invocation
  Commit / Verification Evidence
            │
            ▼
Canonical Business API / Enterprise OS
  Atomic Transaction
  Durable Idempotency
  Write-time Preconditions
  Commit Confirmation
  Verification Support
```

이 경계를 넘어서 NSL Runtime이 Human/Organization/Queue orchestration을 소유하지 않는다.

---

# 27. 대표 전표 Use Case

```text
Input
account_code
project_code
amount
description
transaction_date

READ account
READ project
READ accounting period

CHECK account active
CHECK project active
CHECK period open
CHECK amount > 0

APPROVE

WRITE FINANCE.CREATE_VOUCHER_DRAFT

VERIFY voucher

EMIT voucher_no/status
```

---

# 28. 대표 프로젝트 Use Case

```text
Input
project_name
parent_project_code
start_date
end_date
team_id

READ parent
READ duplicate name/code
CHECK parent active
CHECK period valid
CHECK team authority

APPROVE

WRITE PROJECT.CREATE_PROJECT_DRAFT

VERIFY project

EMIT project_code/status
```

---

# 29. v0.2에서 의도적으로 하지 않는 것

```text
General Transaction Language
try/catch
rollback keyword
arbitrary retry
multiple writes
bulk writes in foreach
dynamic write tool selection
LLM inside Runtime
update/delete

Approval Routing / UI / Notification
Resume Job Scheduling / Queue ownership
Retry / Reconciliation orchestration
Tenant/User Policy authoring
```

위 Control Plane 기능은 NSL의 계약과 evidence를 소비할 수 있으나 NSL Runtime 내부 기능으로 구현하지 않는다.

---

# 29.1 Closure Alignment Trace

본 문서에 적용한 주요 Unified Change Ledger 항목:

```text
CHG-003  BusinessOperationId 도입
CHG-004  IdempotencyKey / PayloadHash 분리
CHG-005  ApprovalRequestId + Approval Evidence binding
CHG-006  Approval workflow ownership → Agent/Platform
CHG-007  PreWriteEligibility에서 Reconciliation 제거
CHG-010  Signed NSP trust boundary 재사용
CHG-011  Approval↔WRITE exactly 1:1
CHG-017  TOCTOU / write-time business preconditions
CHG-018  Checkpoint → Approval publish crash consistency
CHG-023  Risk classification / PolicyDecision 분리
CHG-024  Approval payload protected-reference model
CHG-026  RetrySafety evidence와 actual retry decision 분리
```

이 문서는 이후 SRS/IR/Tool/Compiler/Runtime 문서가 따를 **Cross-Cutting Controlled Write Semantics**를 정의한다.

---

# 30. 최종 정의

> **Controlled Write는 “WRITE keyword”가 아니라, 정적 검증 → 업무 CHECK → 승인 → Payload 고정 → Idempotent Atomic Write → Commit 확인 → 사후 검증까지 포함하는 하나의 실행 프로토콜이다.**

본 문서를 NSL v0.2의 Compiler / IR / Tool Contract / Runtime 개정이 따라야 할 **Cross-Cutting Semantic Architecture** 기준으로 사용한다.  
Normative MUST/SHOULD 요구사항은 SRS가 담당하며, Architecture Closure에서 FROZEN된 결정과 충돌하는 경우 본 문서를 독자적으로 변경하지 않는다.
