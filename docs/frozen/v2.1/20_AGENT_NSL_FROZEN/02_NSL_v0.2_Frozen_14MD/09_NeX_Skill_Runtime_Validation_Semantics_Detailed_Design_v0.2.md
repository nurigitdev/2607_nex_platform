# NSL v0.2 Runtime Validation Semantics Detailed Design

**문서 버전:** v0.2 — Closure Aligned  
**작성일:** 2026-08-23  
**기본 Profile:** `NSL-0.2-STRICT`  
**Architecture Closure 기준:** `NSL v0.2 Architecture Consistency Closure and Unified Change Ledger v1.0 — FROZEN`

---

# 1. 목적

v0.1의 PASS / FAIL / UNKNOWN Semantics를 그대로 유지하면서, Controlled Write 실행 전 허용 여부를 별도의 `PreWriteEligibility` 계층으로 추가한다.

중요 원칙:

> **CHECK 결과, Approval lifecycle, WRITE 실행 전 허용 상태, Commit 결과, Reconciliation 상태를 하나의 Status로 합치지 않는다.**

본 문서는 Runtime의 **Validation / Pre-Write Decision Semantics**를 정의한다. Approval workflow orchestration, Resume Queue, Retry/Reconciliation decision은 Agent/Platform Control Plane의 책임이다.

---

# 2. v0.1 Validation Semantics 유지

```text
TRUE + COMPLETE
→ PASS

FALSE + COMPLETE
→ FAIL

TRUE/FALSE + PARTIAL
→ UNKNOWN

TRUE/FALSE + UNKNOWN completeness
→ UNKNOWN
```

Presence/Completeness 분리도 그대로 유지한다.

---

# 3. Tool Failure 유지

Tool Failure는 Data State가 아니다.

```text
ToolFailure
→ no ValueEnvelope
→ no CHECK evaluation if required input unavailable
```

WRITE에서도 동일 원칙을 유지한다.

---

# 4. PreWriteEligibility 추가

WRITE 이전 허용 판단의 canonical 명칭은 `PreWriteEligibility`다.

```python
class PreWriteEligibility(str, Enum):
    ALLOWED = "ALLOWED"
    BLOCKED = "BLOCKED"
    REQUIRES_APPROVAL = "REQUIRES_APPROVAL"
```

`RECONCILIATION_REQUIRED`는 pre-write eligibility가 아니다.

```text
CommitState == UNKNOWN_COMMIT_STATE
→ ExecutionStatus / Disposition == RECONCILIATION_REQUIRED
```

즉 다음을 분리한다.

```text
ValidationSummary
PreWriteEligibility
ApprovalStatus / ApprovalDecision / ApprovalEvidenceValidation
CommitState
VerificationStatus
ExecutionStatus / Disposition
```

---

# 5. ValidationSummary와 PreWriteEligibility 분리

ValidationSummary와 `PreWriteEligibility`를 분리한다.

예:

```text
ValidationSummary
    ALL_PASS

ApprovalStatus
    PENDING

PreWriteEligibility
    REQUIRES_APPROVAL
```

또는:

```text
ValidationSummary
    HAS_UNKNOWN

PreWriteEligibility
    BLOCKED
```

Approval이 존재하더라도 Required CHECK가 FAIL/UNKNOWN이면 `PreWriteEligibility=BLOCKED`다.

---

# 6. PreWriteEligibility 기본 Rule

```text
Any Required CHECK == FAIL
→ BLOCKED

Any Required CHECK == UNKNOWN
→ BLOCKED

All Required CHECK == PASS
+ Approval missing/pending
→ REQUIRES_APPROVAL

All Required CHECK == PASS
+ Approval Evidence valid
+ RuntimePreflight passed
+ current PolicyDecision allows
+ Tool Preconditions passed
+ write-time Business Preconditions passed
→ ALLOWED
```

Commit 이후 상태는 `PreWriteEligibility`에 되돌려 넣지 않는다.

```text
CommitState UNKNOWN_COMMIT_STATE
→ ExecutionStatus / Disposition RECONCILIATION_REQUIRED
```

또한 `BusinessOperationId`는 Suspend/Resume/Re-execution/Reconciliation 동안 동일 업무 WRITE를 안정적으로 식별하는 Runtime identity로 유지되어야 한다.

---

# 7. UNKNOWN → WRITE 금지

v0.1에서 UNKNOWN은 보고 가능한 Business Validation Outcome이었다.

v0.2에서는 READ-only 실행은 UNKNOWN으로 완료할 수 있으나, WRITE가 예정되어 있으면:

```text
UNKNOWN
→ no approval-to-write transition
→ BLOCKED
```

이 원칙은 절대적인 v0.2 Safety Invariant다.

---

# 8. Approval과 CHECK

Approval은 CHECK 실패를 덮어쓸 수 없다.

금지:

```text
CHECK FAIL
+ Human Approved
→ WRITE
```

허용:

```text
CHECK all PASS
+ Human Approved
→ WRITE
```

Approval은 Policy Override가 아니라 Side Effect Permission Gate다.

---

# 9. ApprovalStatus

Approval lifecycle state:

```text
NOT_REQUESTED
PENDING
APPROVED
REJECTED
EXPIRED
```

Human decision은 lifecycle state와 분리할 수 있다.

```text
ApprovalDecision
APPROVED
REJECTED
```

Approval Evidence 자체의 검증 결과도 별도 의미를 가진다.

```text
ApprovalEvidenceValidation
VALID
INVALID
EXPIRED
INTENT_MISMATCH
PAYLOAD_MISMATCH
BUSINESS_OPERATION_MISMATCH
APPROVAL_REQUEST_MISMATCH
```

예:

```text
ApprovalStatus = APPROVED
ApprovalEvidenceValidation = INTENT_MISMATCH
→ PreWriteEligibility = BLOCKED
```

REJECTED:

```text
PreWriteEligibility = BLOCKED
```

EXPIRED:

```text
PreWriteEligibility = REQUIRES_APPROVAL
```

`INVALID`를 `ApprovalStatus` 값으로 추가하지 않아 lifecycle과 evidence validation을 섞지 않는다.

---

# 10. Signature / Policy와 Eligibility

다음은 `ALLOWED` 전제조건을 구성하지만 책임은 계층별로 분리한다.

```text
RuntimePreflight
  Verified Signed NSP / Package Trust Evidence
  Tool Contract Hash Match
  Tool Capability WRITE
  Atomicity ATOMIC
  Idempotency Supported
  Feature / IR Version Support

WriteGuard / Pre-Write Decision
  Required Checks All PASS
  Approval Evidence Valid
  Current PolicyDecision Allowed
  Write Intent / Payload Binding Valid
  Write-time Business Preconditions PASS
  Replay Live-Write Prohibition satisfied
```

`RiskLevel`은 static classification metadata이며, User/Tenant별 실제 allow/deny는 외부 Policy/OA의 `PolicyDecision`으로 처리한다.

따라서 RuntimePreflight와 WriteGuard가 동일한 검사를 무분별하게 중복하지 않는다.

---

# 11. Write Intent Validation

Approval 시 계산한 `write_intent_hash`와 Resume 시 계산한 Hash가 동일해야 한다.

Approval Evidence는 최소 다음 실행 identity와 binding되어야 한다.

```text
BusinessOperationId
ApprovalRequestId
ApprovalId
Skill Semantic Hash
PayloadHash
WriteIntentHash
```

Resume 시:

```text
write_intent_hash mismatch
→ ApprovalEvidenceValidation = INTENT_MISMATCH
→ PreWriteEligibility = BLOCKED
→ Reason = APPROVAL_INTENT_MISMATCH
```

또는:

```text
BusinessOperationId mismatch
→ ApprovalEvidenceValidation = BUSINESS_OPERATION_MISMATCH
→ PreWriteEligibility = BLOCKED

ApprovalRequestId mismatch
→ ApprovalEvidenceValidation = APPROVAL_REQUEST_MISMATCH
→ PreWriteEligibility = BLOCKED

PayloadHash mismatch
→ ApprovalEvidenceValidation = PAYLOAD_MISMATCH
→ PreWriteEligibility = BLOCKED
```

Payload 자체가 바뀌어야 한다면 기존 Approval을 재사용하지 않고 새로운 WriteIntent와 ApprovalRequest를 생성해야 한다.

---

# 12. Commit State는 Validation Status가 아님

```text
COMMITTED
NOT_COMMITTED
UNKNOWN_COMMIT_STATE
```

는 Write Execution Outcome이다.

CHECK Status와 혼합하지 않는다.

---

# 13. UNKNOWN_COMMIT_STATE

```text
Tool Provider Result uncertain
→ CommitState UNKNOWN_COMMIT_STATE
→ ExecutionStatus / Disposition RECONCILIATION_REQUIRED
```

`UNKNOWN_COMMIT_STATE`는 Validation 또는 PreWriteEligibility가 아니다.

Runtime은 자동 Retry하지 않는다.

Cancellation/Timeout 역시 Provider 호출 이후 Commit 여부가 확실하지 않다면 다음처럼 처리한다.

```text
Provider 미호출이 확실
→ NOT_COMMITTED / CANCELLED 가능

Provider 호출 이후 Commit 여부 불명
→ UNKNOWN_COMMIT_STATE
→ RECONCILIATION_REQUIRED
```

Commit uncertainty를 단순 `FAILED` 또는 `CANCELLED`로 축소해서는 안 된다.

---

# 14. Post-Write Verification

Verification은 CHECK처럼 보일 수 있지만 의미가 다르다.

```text
COMMITTED
→ verification READ
→ VerificationStatus
```

권장:

```text
NOT_REQUESTED
VERIFIED
FAILED
UNKNOWN
```

Verification 실패가 Commit을 되돌리지는 않는다.

따라서 다음을 분리한다.

```text
CommitState
VerificationStatus
```

예:

```text
CommitState = COMMITTED
VerificationStatus = FAILED
```

이어도 CommitState를 `NOT_COMMITTED`로 재분류하거나 자동 WRITE를 재실행하지 않는다.

---

# 15. VerificationStatus

권장 canonical type:

```text
NOT_REQUESTED
VERIFIED
FAILED
UNKNOWN
```

`FAILED`는 "Business Object가 생성되지 않았다"와 동일하지 않다.

```text
CommitState = COMMITTED
VerificationStatus = FAILED / UNKNOWN
```

이면 운영 확인 또는 Platform-level reconciliation이 필요할 수 있지만, NSL Runtime이 동일 WRITE를 자동 Retry하지 않는다.

---

# 16. Validation Summary v0.2

기존:

```text
ALL_PASS
HAS_FAIL
HAS_UNKNOWN
HAS_FAIL_AND_UNKNOWN
NO_CHECK
```

유지.

PreWriteEligibility는 별도 필드다.

---

# 17. CHECK Required 여부

v0.2에서는 WRITE Guard에 영향을 주는 CHECK를 기본적으로 required로 취급한다.

향후 advisory check를 추가할 수 있으나 `NSL-0.2-STRICT`에서는 모든 CHECK를 write-precondition으로 취급하는 단순 정책을 유지한다.

다만 Approval 대기 이후 External Business State가 바뀔 수 있으므로, Approval 시점의 CHECK PASS만으로 write-time freshness가 보장되지는 않는다.

WRITE 직전에는 Canonical Business API 또는 equivalent provider boundary에서 다음과 같은 Business Preconditions를 재검증해야 한다.

```text
version / revision
ETag / precondition token
transactional business revalidation
equivalent provider-side precondition
```

Approval TTL만으로 TOCTOU 문제를 해결했다고 간주하지 않는다.

---

# 18. False Write Safety Invariants

```text
FW-01 ToolFailure → no PASS
FW-02 PARTIAL → no PASS
FW-03 UNKNOWN completeness → no PASS
FW-04 UNKNOWN → no WRITE
FW-05 FAIL → no WRITE
FW-06 Approval cannot override FAIL/UNKNOWN
FW-07 Untrusted/invalid package trust evidence → no Production WRITE
FW-08 Payload / WriteIntent / Approval Evidence mismatch → no WRITE
FW-09 UNKNOWN commit → no automatic retry
FW-10 Replay → no live control-plane decision / no live WRITE
FW-11 Approval Evidence BusinessOperationId mismatch → no WRITE
FW-12 ApprovalRequestId mismatch → no WRITE
FW-13 Write-time Business Preconditions fail → no WRITE
FW-14 Provider call 이후 Cancellation/Timeout + unknown commit → RECONCILIATION_REQUIRED
```

이 Invariant들은 Runtime implementation option으로 완화해서는 안 된다.

---

# 19. Voucher Example

```text
ACCOUNT_VALID     PASS
PROJECT_VALID     PASS
PERIOD_OPEN       PASS
AMOUNT_VALID      PASS

ValidationSummary
ALL_PASS

Approval
PENDING

PreWriteEligibility
REQUIRES_APPROVAL
```

Approval 후:

```text
Approval
APPROVED

PreWriteEligibility
ALLOWED
```

---

# 20. Partial Account Data Example

```text
ACCOUNT.GET_ACCOUNT
PARTIAL/UNKNOWN

CHECK ACCOUNT_VALID
UNKNOWN

PreWriteEligibility
BLOCKED
```

사람이 승인해도 WRITE할 수 없다.

---

# 21. Runtime API 권장 Result

ExecutionResult에는 다음을 분리해서 포함한다.

```text
validation
pre_write_eligibility
approval
write
verification
```

위 public field name은 Runtime Python Interface의 canonical `ExecutionResult`와 일치한다. `approval`/`write`/`verification` 필드는 각각 Summary DTO를 담는다.

Approval/WRITE가 없는 READ-only 실행에서는 v0.2 WRITE 관련 필드를 `None` 또는 Not Applicable 의미로 둘 수 있어야 한다.

v0.1 Result의 validation/evidence/output/resource/error 의미를 제거하지 않고 additive하게 확장한다.

---

# 22. Replay

Replay는 같은 Input/Snapshot에서 같은 결과를 재현해야 한다.

Replay Snapshot에는 WRITE Outcome뿐 아니라 실행 결과에 영향을 준 Control Evidence를 포함한다.

```text
Tool Read Snapshot
Approval Evidence Snapshot
Policy Decision Snapshot
Verified Package / Trust Evidence
Write Outcome Snapshot
Verification Outcome Snapshot
```

Replay에서는 다음을 금지한다.

```text
새 Idempotency Key 생성
Live Approval/Policy decision 호출
Live WRITE 호출
현재 환경의 Trust Decision으로 과거 실행 의미 변경
```

즉:

> **Replay = no live control-plane decision calls + no live WRITE**

---

# 22.1 Approval Payload Protection

Approval Request/Event/Audit에는 raw WRITE payload를 기본적으로 복제하지 않는다.

권장 구조:

```text
display_safe_summary
protected_payload_ref
payload_hash
data_classification
```

상세 Payload가 필요한 경우 tenant isolation / access control이 적용된 protected snapshot을 조회한다.

Approval Evidence는 상세 Payload 자체보다 `PayloadHash`, `WriteIntentHash`, `BusinessOperationId`, `ApprovalRequestId`에 binding되어야 한다.

---

# 22.2 Closure Alignment Trace

본 문서에 적용한 주요 Unified Change Ledger 항목:

```text
CHG-003  BusinessOperationId runtime identity 반영
CHG-005  ApprovalRequestId + Evidence Binding
CHG-007  PreWriteEligibility에서 Reconciliation 제거
CHG-017  TOCTOU / Write-time Business Preconditions
CHG-020  Cancellation/Timeout Commit Uncertainty Rule
CHG-021  RuntimePreflight / WriteGuard Responsibility 분리
CHG-023  Risk Classification / PolicyDecision 분리
CHG-024  Approval Payload Protected-reference Model
CHG-025  Replay Control-Evidence Snapshot
CHG-028  ApprovalStatus / Decision / EvidenceValidation 분리
CHG-029  VerificationStatus typed + CommitState 분리
```

본 문서는 위 Closure 결정을 Runtime Validation / Pre-Write Decision 의미론으로 구체화한다.

---

# 23. 최종 정의

> **NSL v0.2에서 PASS는 업무 규칙이 만족됐다는 뜻이고, APPROVED는 사람이 특정 BusinessOperation의 Side Effect를 허가했다는 뜻이며, ALLOWED는 Runtime이 현재 Evidence·Policy·Business Preconditions 기준으로 실제 WRITE를 실행해도 된다는 최종 pre-write 안전 상태이다. Commit과 Reconciliation은 그 이후의 별도 lifecycle이다.**
