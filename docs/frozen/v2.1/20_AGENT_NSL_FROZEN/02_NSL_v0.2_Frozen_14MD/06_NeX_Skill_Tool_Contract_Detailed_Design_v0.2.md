# NeX Skill Tool Contract Detailed Design v0.2

**문서 버전:** v0.2 — Closure Aligned  
**작성일:** 2026-08-23  
**대상:** NSL v0.2 READ / WRITE Tool  
**기본 Profile:** `NSL-0.2-STRICT`  
**Architecture Closure 기준:** `NSL v0.2 Architecture Consistency Closure and Unified Change Ledger v1.0 — FROZEN`

---

# 1. 목적

v0.1의 **Canonical Tool Contract / Customer Runtime Binding 분리**를 유지하면서 Controlled WRITE에 필요한 실행 계약을 additive하게 확장한다.

```text
NSL Source / IR
      ↓
Canonical Tool Contract
      ↓
Runtime Tool Resolution
      ↓
Customer Tool Binding
      ↓
MCP / Canonical Business API
      ↓
ERP / Business System
```

본 문서의 핵심 Closure 원칙:

```text
Tool Contract
= provider-independent semantic contract

Tool Binding
= endpoint / credential / customer/provider mapping

BusinessOperationId / IdempotencyKey / PayloadHash
= runtime invocation identity/evidence

PolicyDecision
= external Policy/OA result

CommitState
= provider/business execution outcome
```

v0.2 확장은 v0.1 Contract Schema를 깨뜨리지 않고 **기존 field shape에 WRITE semantic field를 additive하게 추가**해야 한다.

---

# 2. 핵심 원칙

1. Canonical Tool ID는 구현체와 Customer Binding에 독립적이어야 한다.
2. Compiler는 Canonical Contract만 Resolve하고 Binding은 Runtime이 Resolve한다.
3. READ/WRITE 모두 Success/Failure를 명시적으로 구분한다.
4. WRITE는 Capability/OperationKind/Risk/Atomicity/Idempotency/Commit/Verification Semantics를 명시해야 한다.
5. `UNKNOWN_COMMIT_STATE`를 일반 Tool Failure로 숨기지 않는다.
6. Provider-specific Transaction/Endpoint/Credential/Mapping은 Adapter/Business API/Binding이 책임진다.
7. Replay는 동일 Semantic Contract를 따르되 Live Side Effect를 만들지 않는다.
8. `BusinessOperationId`, `IdempotencyKey`, `PayloadHash`는 Contract Definition 자체가 아니라 Runtime Call Request의 identity/evidence다.
9. `IdempotencyKey`와 `PayloadHash`는 서로 다른 의미이며 결합해서 하나의 identity로 만들지 않는다.
10. RiskLevel은 static classification metadata이고 Tenant/User별 allow/deny는 외부 PolicyDecision이다.
11. WRITE 직전 Business Preconditions는 Canonical Business API가 atomic transaction 경계 안에서 검증할 수 있어야 한다.
12. Retry 가능성은 Tool Contract가 `RetrySafety` evidence를 제공할 수 있으나 실제 Retry 결정은 Agent/Platform Control Plane이 담당한다.

---

# 3. Tool Contract Top-Level v0.2

v0.1의 canonical field shape를 유지한다.

```json
{
  "tool_id": "FINANCE.CREATE_VOUCHER_DRAFT",
  "version": "1.0.0",
  "capability": "WRITE",
  "operation_kind": "CREATE_DRAFT",
  "risk_level": "R3",

  "inputs": [
    {
      "name": "account_code",
      "type": {"kind": "domain", "name": "AccountCode"},
      "required": true
    }
  ],

  "output": {},
  "result_semantics": {},
  "execution_semantics": {},
  "write_semantics": {},
  "security": {},
  "compatibility": {}
}
```

중요:

```text
v0.1 canonical schema:
"inputs": [...]

v0.2:
위 구조를 유지하고 WRITE field를 additive하게 확장
```

문서 편의를 위해 `"input": {"fields": [...]}`와 같은 별도 parallel schema를 새로 만들지 않는다.

---

# 4. Capability

공유 `ToolCapability`를 사용한다.

```text
READ
WRITE
TRANSACTION   # reserved / future
```

NSL v0.2 Source의 `write`는 `capability=WRITE`만 허용한다.

Capability는 Tool의 semantic capability이고, 특정 Principal/Tenant가 현재 해당 Tool을 실행할 수 있는지는 별도의 external PolicyDecision이다.

---

# 5. Operation Kind

v0.2에서 허용하는 WRITE OperationKind:

```text
CREATE
CREATE_DRAFT
```

향후 후보:

```text
UPDATE
DELETE
CANCEL
POST
FINALIZE
```

는 별도 Language/Contract Version에서 검토한다.

OperationKind는 raw string의 임의 확장값보다 shared typed/bounded model로 관리하는 것을 권장한다.

---

# 6. Risk Level

권장 Risk Classification:

```text
R0 pure
R1 read
R2 sensitive read
R3 draft write
R4 business write
R5 final/external transaction
```

`RiskLevel`은 Tool/Skill의 **static classification metadata**다.

```text
Compiler
→ Risk metadata의 존재/형식/계약 정합성 검증

Runtime
→ current external PolicyDecision 검증

Policy/OA
→ tenant/user entitlement, MFA, 조직별 추가 조건 판단
```

Risk classification 자체를 User/Tenant allow/deny 결정으로 사용하지 않는다.

---

# 7. WRITE Input Schema

v0.1의 `inputs: [...]` TypeInfo 기반 schema를 유지한다.

전표 예:

```json
{
  "inputs": [
    {
      "name": "account_code",
      "type": {"kind": "domain", "name": "AccountCode"},
      "required": true
    },
    {
      "name": "project_code",
      "type": {"kind": "domain", "name": "ProjectCode"},
      "required": true
    },
    {
      "name": "amount",
      "type": {"kind": "money", "currency": "KRW"},
      "required": true
    }
  ]
}
```

WRITE라고 해서 v0.1 READ Tool과 다른 parallel input schema를 만들지 않는다.

Payload의 runtime canonical serialization과 `PayloadHash` 계산은 Runtime/Tool Call 단계의 책임이다.

---

# 8. WRITE Output

WRITE 결과는 **Business Result**와 **Execution Metadata**를 분리한다.

Logical Business Result 예:

```text
VoucherDraft
ProjectDraft
```

Runtime Write Result Metadata 예:

```text
business_operation_id
business_reference
commit_state
idempotency_key
payload_hash
provider_transaction_id
committed_at
```

`VerificationStatus`는 `CommitState`와 독립적으로 관리한다.

```text
commit_state = COMMITTED
verification_status = FAILED
```

이어도 Commit을 NOT_COMMITTED로 재분류하지 않는다.

---

# 9. Write Semantics

권장 additive extension:

```json
{
  "write_semantics": {
    "side_effect": true,
    "atomicity": "ATOMIC",

    "idempotency": {
      "required": true,
      "scope": "TOOL_AND_TENANT",
      "retention": "PROVIDER_DEFINED",
      "duplicate_behavior": "RETURN_ORIGINAL_RESULT",
      "payload_conflict_behavior": "IDEMPOTENCY_CONFLICT"
    },

    "commit": {
      "confirmation": "EXPLICIT"
    },

    "approval": {
      "required": true
    },

    "preconditions": {
      "supported": true,
      "enforcement": "PROVIDER_TRANSACTION_BOUNDARY"
    },

    "verification": {
      "recommended": true,
      "tool_id": "FINANCE.GET_VOUCHER"
    }
  }
}
```

`approval.required=true`는 Tool의 semantic minimum requirement를 나타낸다. 실제 ApprovalRequest 생성·Routing·UI·Persistence·Resume scheduling은 Tool Provider가 소유하지 않는다.

`preconditions`는 WRITE 시점의 business state를 다시 확인할 수 있는 contract capability를 표현한다. Approval TTL만으로 freshness를 보장하지 않는다.

---

# 10. Atomicity

`NSL-0.2-STRICT`의 WRITE Tool은:

```text
ATOMIC
```

이어야 한다.

```text
BEST_EFFORT
PARTIAL_COMMIT
```

형태는 Compiler/RuntimePreflight에서 거부한다.

예를 들어 전표 Header/Line 생성은 Canonical Business API 내부의 **하나의 business transaction boundary**로 처리한다.

NSL Runtime이 generic rollback/compensation을 가정하지 않는다.

---

# 11. Idempotency

WRITE Contract는 최소 다음 semantic capability를 선언한다.

```text
required
scope
retention
duplicate_behavior
payload_conflict_behavior
```

Runtime identity/evidence는 분리한다.

```text
BusinessOperationId
        │
        └─ stable business operation identity

IdempotencyKey
        │
        └─ duplicate domain key

PayloadHash
        │
        └─ canonical request payload identity
```

규칙:

```text
동일 IdempotencyKey + 동일 PayloadHash
→ Original Business Result 반환

동일 IdempotencyKey + 다른 PayloadHash
→ IDEMPOTENCY_CONFLICT
```

Durable duplicate guarantee는 Canonical Business API/Provider가 책임진다.

---

# 12. ToolCallRequest v0.2

READ Call과 WRITE Call은 공통 Tool Call 모델을 공유할 수 있으나, WRITE 경계에서는 다음 identity/evidence를 명시적으로 전달할 수 있어야 한다.

권장 `WriteCallRequest` logical fields:

```text
execution_id
business_operation_id
invocation_id
node_id

tool_ref
arguments

idempotency_key
payload_hash

approval_request_id
write_intent_hash

call_context
precondition_evidence(optional)
```

중요:

```text
BusinessOperationId ≠ execution_id ≠ invocation_id
IdempotencyKey ≠ PayloadHash
```

Provider에는 업무 처리를 위해 필요한 최소 정보만 전달한다.

Approval Evidence 원문 전체를 Provider에 전달할 필요는 없으며, 필요한 경우 검증된 reference/claim만 전달한다.

---

# 13. Commit State

공유 `CommitState`를 사용한다.

```text
COMMITTED
NOT_COMMITTED
UNKNOWN_COMMIT_STATE
```

예:

```text
Provider 호출 이전 local validation failure
→ NOT_COMMITTED

Provider가 request를 수신하지 않았음을 명시적으로 보장
→ NOT_COMMITTED 가능

Provider 호출 이후 timeout / connection loss
+ upstream commit 여부 확인 불가
→ UNKNOWN_COMMIT_STATE
```

Provider Adapter는 확실하지 않은 상태를 임의로 `NOT_COMMITTED`로 축소하면 안 된다.

Cancellation/Timeout 역시 Provider 호출 이후 commit 여부가 불명확하면 `UNKNOWN_COMMIT_STATE`로 보존한다.

---

# 14. Write Tool Outcome

Canonical WRITE outcome algebra는 3-way로 고정한다.

```text
WriteExecutionOutcome
├─ WriteCommitted
│   └─ WriteResultEnvelope
│
├─ WriteNotCommitted
│   └─ ToolError / business conflict evidence
│
└─ WriteCommitUnknown
    └─ Commit uncertainty evidence
```

별도 `WriteFailure` variant를 추가하여 commit 여부를 다시 흐리게 만들지 않는다.

모든 WRITE attempt의 핵심 질문은 다음이다.

```text
Committed?
  YES
  NO
  UNKNOWN
```

`UNKNOWN_COMMIT_STATE`는 일반 ToolFailure에 숨기지 않는다.

---

# 15. Error Taxonomy v0.2

기존 Error Taxonomy에 WRITE 관련 code를 additive하게 추가한다.

```text
APPROVAL_REQUIRED
APPROVAL_INVALID
APPROVAL_INTENT_MISMATCH

IDEMPOTENCY_CONFLICT

WRITE_POLICY_DENIED
WRITE_PRECONDITION_FAILED
ATOMICITY_NOT_SUPPORTED

COMMIT_NOT_CONFIRMED
UNKNOWN_COMMIT_STATE

POST_WRITE_VERIFICATION_FAILED
BUSINESS_CONFLICT
```

Error code와 `CommitState`는 같은 의미가 아니다.

예:

```text
POST_WRITE_VERIFICATION_FAILED
+ CommitState.COMMITTED

UNKNOWN_COMMIT_STATE
+ Reconciliation required
```

처럼 함께 존재할 수 있다.

---

# 16. Retry Policy

READ Retry와 WRITE Retry는 다르게 취급한다.

Tool Contract는 실제 Retry를 수행하는 명령이 아니라 **RetrySafety evidence를 계산할 수 있는 semantic metadata**를 제공한다.

예:

```text
Tool Contract retry-safe
AND
Idempotency supported
AND
CommitState == NOT_COMMITTED
→ SAFE_TO_RETRY evidence 가능
```

다음은 절대 자동 Retry 대상이 아니다.

```text
CommitState == UNKNOWN_COMMIT_STATE
```

실제 Retry 여부와 시점은 Agent/Platform Control Plane이 결정한다.

NSL Runtime과 Tool Adapter가 독자적으로 blind retry를 수행해서는 안 된다.

---

# 17. Post-Write Verification

Tool Contract는 다음 중 하나 이상을 제공할 수 있다.

```text
verification_tool_id
verification_reference_schema
read_after_write consistency hint
```

Verification Tool은 일반 READ Contract를 사용한다.

공유 `VerificationStatus` 예:

```text
NOT_REQUESTED
VERIFIED
FAILED
UNKNOWN
```

`VerificationStatus`와 `CommitState`는 독립적이다.

```text
COMMITTED + FAILED
```

는 Commit을 되돌리지 않으며 자동 WRITE Retry의 근거가 아니다.

---

# 18. Security

Canonical Tool Contract의 `security` 영역에는 **Tool 자체의 provider-independent semantic security requirement**만 포함한다.

예:

```text
required_scope
data_classification
credential_capability_required
audit_requirement
```

다음 환경별 결정값은 Canonical Tool Contract semantic hash에 하드코딩하지 않는다.

```text
specific user/role allowlist
tenant entitlement
current MFA state
network allowlist
organization-specific approval routing
customer endpoint credential mapping
```

위 값들은 Policy/OA 또는 Customer Binding에서 결정하며 Runtime은 current `PolicyDecision` / Policy Evidence를 검증한다.

즉:

```text
RiskLevel / required_scope
= static contract semantics

PolicyDecision
= current execution authorization
```

으로 분리한다.

---

# 19. Contract Hash v0.2

다음 **provider-independent semantic contract**가 바뀌면 `contract_hash`가 변경되어야 한다.

```text
inputs / output
capability
operation_kind
risk_level
required_scope / semantic security requirement
atomicity
idempotency semantics
commit semantics
approval requirement
business precondition capability
verification semantics
```

다음은 Canonical Contract Hash에 포함하지 않고 Binding/Policy 영역에 둔다.

```text
endpoint
credential
customer/provider mapping
tenant/user allowlist
current MFA state
network allowlist
organization-specific policy decision
```

Contract Hash는 실행 시 RequiredTool fingerprint와 현재 resolved Canonical Contract의 정합성을 검증하는 데 사용한다.

---

# 20. Tool Binding v0.2

Customer Tool Binding은 provider-specific 실행 정보를 소유한다.

추가 가능:

```text
endpoint / transport mapping
credential reference
provider idempotency header mapping
provider payload field mapping
provider transaction reference mapping
commit state mapping
precondition token / revision mapping
verification binding
```

NSL Source와 Static IR은 이를 알지 않는다.

Binding이 Canonical Contract semantic meaning을 바꾸어서는 안 된다.

---

# 21. Runtime WRITE Pipeline

```text
ExecutionRequest
  Principal / DataPolicy
  BusinessOperationId
        ↓
IR WriteExpression
        ↓
WriteGuard
  CHECK / Approval Evidence
  Current PolicyDecision
  Contract / Capability
  Business Preconditions
        ↓
IdempotencyKey + PayloadHash
        ↓
Durable WRITE_REQUESTED
        ↓
ToolResolver / Binding
        ↓
WriteCallRequest
        ↓
ProviderInvoker
        ↓
Canonical Outcome Mapping
   ┌──────────┬──────────────┬──────────────────┐
   ▼          ▼              ▼
COMMITTED  NOT_COMMITTED  UNKNOWN_COMMIT_STATE
   │                          │
   ▼                          ▼
Verification           RECONCILIATION_REQUIRED
```

Provider 호출 전에 최소 다음 evidence를 durable하게 기록할 수 있어야 한다.

```text
business_operation_id
idempotency_key
payload_hash
invocation_id
tool_id / node_id
```

Terminal outcome이 없는 상태에서 Runtime process가 종료된 경우 blind re-invoke하지 않고 reconciliation/idempotency query 경로로 전환한다.

---

# 22. Account Master Search

600개 계정과목 문제는 READ Tool로 모델링한다.

예:

```text
ACCOUNT.SEARCH_ACCOUNT_CODES
ACCOUNT.GET_ACCOUNT
```

WRITE Tool과 분리한다.

NeX-AE가 Candidate를 선택하더라도 NSL은 `ACCOUNT.GET_ACCOUNT`와 CHECK를 통해 최종 유효성을 검증할 수 있다.

단, Approval 대기 중 External State가 바뀔 수 있으므로 WRITE Transaction 시점의 Business Preconditions는 Canonical Business API가 다시 확인한다.

---

# 23. Replay

Replay Provider/Executor는 Recorded WRITE Outcome을 반환한다.

```text
Live ERP / Business API WRITE 호출
→ 금지
```

Replay Snapshot에는 최소 다음 WRITE evidence를 보존할 수 있다.

```text
business_operation_id
idempotency_key
payload_hash
commit_state
provider_transaction_id
verification_status / verification outcome
```

Control Plane의 Approval/Policy/Trust evidence replay는 Runtime Architecture가 담당하며, Tool Provider는 기록된 Write Outcome을 재현한다.

> Replay Tool Layer = **no live provider WRITE**

---

# 24. Mock

Mock WRITE Tool/Executor는 최소 다음 scenario를 테스트할 수 있어야 한다.

```text
COMMITTED
NOT_COMMITTED
UNKNOWN_COMMIT_STATE

IDEMPOTENCY_DUPLICATE_SAME_PAYLOAD
IDEMPOTENCY_CONFLICT

WRITE_PRECONDITION_FAILED
BUSINESS_CONFLICT

VERIFICATION_FAILED
VERIFICATION_UNKNOWN

TIMEOUT_BEFORE_PROVIDER
TIMEOUT_AFTER_PROVIDER_WITH_UNKNOWN_COMMIT
```

Mock도 Production의 3-way Commit algebra를 따라야 한다.

---

# 25. 대표 전표 Contract

```text
FINANCE.CREATE_VOUCHER_DRAFT

capability           WRITE
operation_kind       CREATE_DRAFT
risk_level           R3

inputs               v0.1-compatible "inputs": [...]

atomicity             ATOMIC

idempotency.required  true
duplicate_behavior    RETURN_ORIGINAL_RESULT
payload_conflict      IDEMPOTENCY_CONFLICT

approval.required     true

preconditions         provider transaction boundary에서 지원

verification          FINANCE.GET_VOUCHER
```

실제 User/Tenant entitlement나 Approval routing rule은 이 Canonical Contract에 하드코딩하지 않는다.

---

# 26. 대표 프로젝트 Contract

```text
PROJECT.CREATE_PROJECT_DRAFT

capability           WRITE
operation_kind       CREATE_DRAFT
risk_level           R3

inputs               v0.1-compatible "inputs": [...]

atomicity             ATOMIC

idempotency.required  true
duplicate_behavior    RETURN_ORIGINAL_RESULT
payload_conflict      IDEMPOTENCY_CONFLICT

approval.required     true

preconditions         provider transaction boundary에서 지원

verification          PROJECT.GET_PROJECT
```

Project status/version 등 WRITE 시점 business state는 Provider-side precondition으로 재검증할 수 있어야 한다.

---

# 27. v0.2 Contract Invariants

```text
TCW-01 WRITE → side_effect=true
TCW-02 WRITE → atomicity=ATOMIC
TCW-03 WRITE → idempotency.required=true
TCW-04 WRITE → risk_level declared
TCW-05 WRITE → approval requirement declared
TCW-06 WRITE → business precondition capability supported
TCW-07 UNKNOWN commit preserved
TCW-08 Tool failure never becomes empty data
TCW-09 Binding details never enter .nso
TCW-10 IdempotencyKey ≠ PayloadHash
TCW-11 Same key + different PayloadHash → IDEMPOTENCY_CONFLICT
TCW-12 RiskLevel ≠ PolicyDecision
TCW-13 CommitState ≠ VerificationStatus
TCW-14 UNKNOWN_COMMIT_STATE → no blind retry
TCW-15 Canonical Contract keeps v0.1 "inputs" schema shape
TCW-16 environment-specific user/tenant/network policy is not part of canonical semantic contract
```

---

# 27.1 Closure Alignment Trace

본 문서에 적용한 주요 Unified Change Ledger 항목:

```text
CHG-003  BusinessOperationId를 Runtime Call identity에 추가
CHG-004  IdempotencyKey / PayloadHash 분리
CHG-016  v0.1 Tool Contract "inputs" schema additive compatibility 유지
CHG-017  Write-time Business Preconditions
CHG-020  Cancellation/Timeout commit uncertainty 보존
CHG-022  WriteOutcome 3-way canonical algebra
CHG-023  Risk Classification / PolicyDecision 분리
CHG-026  RetrySafety evidence와 actual retry decision 분리
CHG-029  VerificationStatus typed + CommitState 분리
```

본 문서는 위 Closure 결정을 **Canonical Tool Contract / Runtime Binding / Provider Outcome** 경계에서 구체화한다.

---

# 28. 최종 정의

> **NSL v0.2의 WRITE 안전성은 Runtime 하나의 책임이 아니라 Canonical Tool Contract가 Atomicity·Idempotency·Commit·Precondition·Verification Semantics를 provider-independent하게 선언하고, Runtime이 stable operation identity와 evidence를 전달하며, Canonical Business API가 이를 transaction boundary에서 durable하게 보장함으로써 완성된다.**
