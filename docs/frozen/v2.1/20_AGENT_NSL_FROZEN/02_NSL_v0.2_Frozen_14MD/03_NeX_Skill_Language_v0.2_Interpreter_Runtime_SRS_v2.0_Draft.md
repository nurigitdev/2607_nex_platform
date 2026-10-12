# NeX Skill Language v0.2 Interpreter & Runtime Environment
## System Requirements Specification v2.0 Draft

- **문서 버전:** v2.0 Draft — Closure Aligned
- **작성일:** 2026-08-23
- **대상 Language:** NSL v0.2
- **구현 언어:** Python 3.12+
- **연계:** NeX-AE / Agent Platform, MCP Tool Registry, Canonical Business API, Approval Service
- **Source:** `.ns`
- **IR/Object:** `.nso`
- **Package:** `.nsp`
- **NSO IR Version:** 1.1
- **기본 Profile:** `NSL-0.2-STRICT`
- **Architecture Closure 기준:** `NSL v0.2 Architecture Consistency Closure and Unified Change Ledger v1.0 — FROZEN`

---

# 0. 개정 이력

| 버전 | 주요 내용 |
|---|---|
| v1.0 Draft | v0.1 Compiler/Runtime/Validation 기본 요구사항 |
| v1.1 Draft | include, Bool Literal, Shared core/ir, Strict Validation 반영 |
| v2.0 Draft | Controlled WRITE, APPROVE, Suspend/Resume, Idempotency, Commit State, Signed NSP Trust, Risk/Policy 분리 추가 |
| v2.0 Draft — Closure Aligned | Architecture Closure / Unified Change Ledger CHG-001~030 중 SRS 적용 항목 반영 |

---

# 1. 목적

NSL v0.2는 v0.1의 안전한 조회·계산·검증 언어를 확장하여, 기업 시스템에 제한된 Side Effect를 생성할 수 있는 Controlled Write Language를 제공한다.

```text
Natural Language
      ↓
NeX-AE / Agent Platform
Intent / Candidate Selection
BusinessOperationId / Principal / DataPolicy
      ↓
NSL v0.2
READ → CHECK → APPROVE → WRITE → VERIFY → EMIT
      ↓
Canonical Business API / MCP
```

Runtime 내부에서는 LLM을 호출하지 않는다.

본 문서는 NSL v0.2의 **Normative Requirements**를 정의한다. 문서 Authority는 다음과 같이 분리한다.

```text
MASTER_PROMPT
  = Implementation Process / Guardrail

Document Baseline & Upgrade Plan
  = Scope / Version / Document Authority

Frozen Architecture ADR / Controlled Write Architecture
  = Cross-cutting Semantic Architecture

본 SRS
  = Normative MUST / SHOULD Requirements

IR / Tool / Compiler / Runtime Detailed Designs
  = Component-level Design / Interface
```

Architecture Closure에서 FROZEN된 의미론과 충돌하는 경우 본 SRS나 상세 설계가 독자적으로 의미를 변경해서는 안 된다.

---

# 2. 시스템 목표

1. v0.1 `.ns`와 `.nso`를 계속 지원한다.
2. `write`를 이용해 Canonical WRITE Tool을 호출할 수 있어야 한다.
3. `approve`를 이용해 사람 승인 Gate를 명시할 수 있어야 한다.
4. 모든 WRITE는 승인된 Write Intent와 정확히 일치해야 한다.
5. Approval 대기 동안 Worker를 점유하지 않아야 한다.
6. 실행을 Checkpoint로 저장하고 Resume할 수 있어야 한다.
7. 동일 Business WRITE는 Suspend/Resume/Re-execution/Reconciliation 동안 유지되는 `BusinessOperationId`를 가져야 한다.
8. WRITE는 Idempotent해야 하며 `IdempotencyKey`와 `PayloadHash`는 서로 다른 identity로 관리해야 한다.
9. Commit 불확실 상태에서 자동 Retry하지 않아야 한다.
10. CHECK FAIL/UNKNOWN 상태에서는 WRITE하지 않아야 한다.
11. Production WRITE는 기존 Signed NSP Trust Boundary에서 검증된 Skill만 실행해야 한다.
12. Runtime Replay가 실제 Side Effect를 발생시키지 않아야 한다.
13. Tool Contract가 Atomicity/Commit/Verification Semantics를 제공해야 한다.
14. v0.1 Execution Request의 Principal / DataPolicy Security Context를 v0.2에서도 보존해야 한다.
15. WRITE 직전의 Business Preconditions를 재검증하여 Approval 이후 External State 변경에 대응해야 한다.

---

# 3. Scope

## 3.1 포함

v0.1 전체 기능:

```text
include
requires
read
foreach
let
check
emit
limits
true / false
sum / count / min / max
Money
PASS / FAIL / UNKNOWN
Replay / Audit
Principal / DataPolicy
```

v0.2 추가:

```text
write
approve
approved_by
BusinessOperationId
ApprovalRequestId
WAITING_FOR_APPROVAL
Suspend / Resume
Checkpoint
IdempotencyKey / PayloadHash
Commit State
Post-Write Verification
Verified Signed NSP Trust
Risk Classification + External Policy Decision
```

## 3.2 초기 지원 WRITE 범위

```text
CREATE
CREATE_DRAFT
```

초기 비지원:

```text
UPDATE
DELETE
CANCEL
POST / FINALIZE
rollback keyword
retry keyword
multiple write transaction
```

## 3.3 v0.2 Strict 제한

다음 제한은 일반 Compiler Option으로 완화할 수 있는 설정이 아니라 `NSL-0.2-STRICT`의 **immutable Safety Rules**다.

```text
Skill당 WRITE Node 최대 1개
WRITE inside FOREACH 금지
모든 WRITE는 explicit APPROVE 필요
Approval ↔ WRITE exactly 1:1
unused Approval 금지
WRITE Tool은 ATOMIC이어야 함
```

Source Language Version은 authoritative하며 다음 mapping을 따른다.

```text
NSL 0.1 → IR 1.0
NSL 0.2 → IR 1.1
```

Compiler Option으로 Source의 Language Version을 임의 override해서는 안 된다.

---

# 4. Architecture

.ns
 ↓
Compiler
 ├─ Include
 ├─ Symbol / Type
 ├─ Tool Contract
 ├─ Write Safety
 ├─ Approval↔WRITE 1:1
 └─ Resource Bound
 ↓
.nso IR 1.1
 ↓
Signed NSP / Verified Package Boundary
 ↓
Runtime
 ├─ READ
 ├─ CHECK
 ├─ PRE-WRITE ELIGIBILITY
 ├─ APPROVAL REQUEST
 ├─ CHECKPOINT
 ├─ WRITE GUARD
 ├─ IDEMPOTENCY
 ├─ WRITE
 ├─ VERIFY
 └─ EMIT
 ↓
Canonical Business API

Approval / Resume Responsibility:

```text
NSL Runtime
  Write Intent Freeze
       ↓
  ApprovalRequestId
       ↓
  Checkpoint Persist
       ↓
  Approval Request Publish
       ↓
  WAITING_FOR_APPROVAL
       ↓
  Worker exit

----------- Agent / Platform Control Plane -----------

  Approval Routing / UI / Persistence / Notification
       ↓
  Human Decision
       ↓
  Resume Job Scheduling / Enqueue

------------------- NSL Resume -----------------------

  Checkpoint Restore
       ↓
  Approval Evidence / Binding 검증
       ↓
  Current Policy + Business Preconditions
       ↓
  WRITE
```

NSL은 Approval Request/Evidence의 의미론과 Suspend/Resume execution contract를 담당하고, Approval workflow orchestration과 Resume Queue ownership은 Agent/Platform이 담당한다.

---

# 5. Architecture Requirements

| ID | 요구사항 | 우선순위 |
|---|---|---|
| NSL-ARC-201 | Compiler와 Runtime은 Shared `core/`와 `ir/` semantic model을 사용해야 한다. | MUST |
| NSL-ARC-202 | Runtime은 Compiler AST를 참조하지 않아야 한다. | MUST |
| NSL-ARC-203 | Runtime 내부에서 LLM을 호출하지 않아야 한다. | MUST |
| NSL-ARC-204 | 모든 업무시스템 접근은 Tool Executor/Port를 통해야 한다. | MUST |
| NSL-ARC-205 | WRITE는 Canonical Business Tool만 호출해야 한다. | MUST |
| NSL-ARC-206 | Approval 대기는 Worker Blocking 방식이 아니어야 한다. | MUST |
| NSL-ARC-207 | Replay는 Live WRITE Provider를 호출하지 않아야 한다. | MUST |
| NSL-ARC-208 | Approval Routing/UI/Persistence/Notification 및 Resume Job Scheduling은 Agent/Platform Control Plane 책임이어야 한다. | MUST |
| NSL-ARC-209 | NSL Runtime은 Approval Workflow를 orchestrate하지 않고 Approval Request/Evidence semantics와 Suspend/Resume execution contract만 제공해야 한다. | MUST |
| NSL-ARC-210 | Production WRITE는 Signed NSP에서 검증된 Verified Package/Skill Trust Evidence를 기반으로 실행해야 한다. | MUST |
| NSL-ARC-211 | v0.1 Execution Request의 Principal/DataPolicy Security Context를 v0.2에서도 additive하게 보존해야 한다. | MUST |

---

# 6. Source / Lexer Requirements

| ID | 요구사항 |
|---|---|
| NSL-LEX-201 | `write`, `approve`, `approved_by`를 Reserved Keyword로 인식해야 한다. |
| NSL-LEX-202 | v0.1의 `include`, `true`, `false`를 유지해야 한다. |
| NSL-LEX-203 | Identifier/Decimal/Money 관련 기존 규칙을 유지해야 한다. |

---

# 7. Parser / AST Requirements

| ID | 요구사항 |
|---|---|
| NSL-PAR-201 | `WriteExpressionAst`를 생성할 수 있어야 한다. |
| NSL-PAR-202 | `ApproveStatementAst`를 생성할 수 있어야 한다. |
| NSL-PAR-203 | WRITE와 Approval Reference를 Source AST에서 보존해야 한다. |
| NSL-PAR-204 | SourceSpan을 유지해야 한다. |

권장 문법:

```ebnf
approve_stmt
  = "approve" identifier
    "{"
      "message" string_literal ";"
    "}"
  ;

write_expr
  = "write" qualified_name
    "(" arguments? ")"
    "approved_by" identifier
  ;
```

---

# 8. Symbol / Scope Requirements

| ID | 요구사항 |
|---|---|
| NSL-SEM-201 | Approval ID Namespace를 관리해야 한다. |
| NSL-SEM-202 | 중복 Approval ID를 금지해야 한다. |
| NSL-SEM-203 | `approved_by`는 선언된 Approval ID를 Resolve해야 한다. |
| NSL-SEM-204 | Approval Reference는 해당 WRITE보다 앞에 위치해야 한다. |
| NSL-SEM-205 | `NSL-0.2-STRICT`에서는 Approval과 WRITE가 exactly 1:1로 연결되어야 한다. |
| NSL-SEM-206 | WRITE와 연결되지 않은 unused Approval을 허용하지 않아야 한다. |

---

# 9. Type Requirements

기존 Static Type System을 유지한다.

WRITE Argument는 Tool Contract Input Type과 정적으로 일치해야 한다.

| ID | 요구사항 |
|---|---|
| NSL-TYP-201 | WRITE Argument Type을 Compile-time에 검증해야 한다. |
| NSL-TYP-202 | WRITE Result Type은 Tool Contract Output에서 결정해야 한다. |
| NSL-TYP-203 | Approval은 Value Truthiness와 무관한 Control Gate이어야 한다. |
| NSL-TYP-204 | CHECK assert는 정확히 Bool이어야 한다. |

---

# 10. Tool Contract Requirements

| ID | 요구사항 |
|---|---|
| NSL-TOL-201 | WRITE Tool은 capability=WRITE를 선언해야 한다. |
| NSL-TOL-202 | WRITE Tool은 operation_kind를 선언해야 한다. |
| NSL-TOL-203 | WRITE Tool은 idempotency.required=true를 선언해야 한다. |
| NSL-TOL-204 | WRITE Tool은 atomicity를 선언해야 한다. |
| NSL-TOL-205 | WRITE Tool은 commit semantics를 선언해야 한다. |
| NSL-TOL-206 | 가능하면 post-write verification 정보를 제공해야 한다. |
| NSL-TOL-207 | contract_hash에 WRITE semantics가 포함되어야 한다. |

---

# 11. WRITE Requirements

| ID | 요구사항 |
|---|---|
| NSL-WRT-001 | Runtime은 `write`를 Side Effect Tool Invocation으로 실행해야 한다. |
| NSL-WRT-002 | `NSL-0.2-STRICT`에서 Skill당 WRITE는 최대 1개여야 하며 일반 Option으로 완화할 수 없어야 한다. |
| NSL-WRT-003 | WRITE는 FOREACH 내부에서 실행할 수 없어야 하며 일반 Option으로 완화할 수 없어야 한다. |
| NSL-WRT-004 | WRITE는 Tool Contract가 ATOMIC일 때만 허용해야 한다. |
| NSL-WRT-005 | WRITE 실행 전 `PreWriteEligibility`가 ALLOWED여야 한다. |
| NSL-WRT-006 | WRITE Payload와 Write Intent는 Approval Evidence가 승인한 내용과 동일해야 한다. |
| NSL-WRT-007 | WRITE 결과는 CommitState를 포함해야 한다. |
| NSL-WRT-008 | UNKNOWN_COMMIT_STATE에서 자동 재시도하지 않아야 한다. |
| NSL-WRT-009 | WRITE 직전 현재 Business Preconditions를 검증해야 한다. |
| NSL-WRT-010 | Approval 이후 Payload를 변경해야 하는 경우 기존 Approval Evidence를 재사용하지 않고 새로운 WriteIntent/Approval Request를 생성해야 한다. |
| NSL-WRT-011 | Business Preconditions는 version/revision, ETag/precondition token, transactional business revalidation 또는 동등한 provider-side mechanism으로 검증할 수 있어야 한다. |

---

# 12. Approval Requirements

| ID | 요구사항 |
|---|---|
| NSL-APR-001 | 모든 WRITE는 `approve`와 exactly 1:1로 연결되어야 한다. |
| NSL-APR-002 | Approval Request는 정적 `ApprovalId`와 실행 instance `ApprovalRequestId`를 구분해야 한다. |
| NSL-APR-003 | Approval Request/Evidence는 `BusinessOperationId`, `ApprovalRequestId`, `skill_semantic_hash`, `write_intent_hash`에 Binding되어야 한다. |
| NSL-APR-004 | Approval 대기 시 Execution을 WAITING_FOR_APPROVAL로 전환해야 한다. |
| NSL-APR-005 | Runtime은 Approval Request를 publish하기 전에 Checkpoint를 durable하게 저장해야 한다. |
| NSL-APR-006 | Approval Request publish는 `ApprovalRequestId`를 기준으로 idempotent해야 한다. |
| NSL-APR-007 | Runtime Worker는 Checkpoint 저장과 Approval Request publish 후 종료할 수 있어야 한다. |
| NSL-APR-008 | Approval Routing/UI/Persistence/Notification 및 Resume Job 생성은 Agent/Platform이 담당해야 한다. |
| NSL-APR-009 | Resume 시 Approval Evidence의 integrity와 BusinessOperationId/ApprovalRequestId Binding을 검증해야 한다. |
| NSL-APR-010 | Resume 시 Approval Evidence의 `write_intent_hash`는 현재 계산한 `write_intent_hash`와 일치해야 한다. |
| NSL-APR-011 | Resume 시 Approval 대상 PayloadHash는 현재 Canonical PayloadHash와 일치해야 한다. |
| NSL-APR-012 | REJECTED Approval에서는 WRITE하지 않아야 한다. |
| NSL-APR-013 | Expired Approval은 재승인을 요구해야 한다. |
| NSL-APR-014 | Approval Event/Queue/Audit에는 raw WRITE Payload를 기본 복제하지 않고 `display_safe_summary`, `protected_payload_ref`, `payload_hash`, `data_classification` 중심으로 전달해야 한다. |

---

# 13. Write Eligibility Requirements

`WriteEligibility`는 WRITE 이전 판단을 의미하므로 본 SRS에서는 `PreWriteEligibility`로 정규화한다.

```text
ALLOWED
BLOCKED
REQUIRES_APPROVAL
```

`RECONCILIATION_REQUIRED`는 Pre-write Eligibility가 아니라 post-write `ExecutionStatus / Disposition`이다.

| ID | 요구사항 |
|---|---|
| NSL-WEL-001 | Required CHECK 중 FAIL이 있으면 BLOCKED여야 한다. |
| NSL-WEL-002 | Required CHECK 중 UNKNOWN이 있으면 BLOCKED여야 한다. |
| NSL-WEL-003 | CHECK가 모두 PASS라도 Approval Evidence가 아직 없거나 Pending이면 REQUIRES_APPROVAL이어야 한다. |
| NSL-WEL-004 | Approval Evidence, current PolicyDecision, Tool Preconditions 중 하나라도 WRITE를 허용하지 않으면 ALLOWED가 되어서는 안 된다. |
| NSL-WEL-005 | UNKNOWN_COMMIT_STATE를 PreWriteEligibility 값으로 표현해서는 안 된다. |

---

# 14. Idempotency Requirements

| ID | 요구사항 |
|---|---|
| NSL-IDM-001 | 모든 WRITE invocation은 IdempotencyKey를 가져야 한다. |
| NSL-IDM-002 | 동일 업무 WRITE를 식별하는 stable `BusinessOperationId`는 Suspend/Resume/Re-execution/Reconciliation 동안 유지되어야 한다. |
| NSL-IDM-003 | IdempotencyKey는 최소한 Tenant/BusinessOperationId/WriteNode identity에 안정적으로 연결되어야 한다. |
| NSL-IDM-004 | PayloadHash는 Canonical WRITE Payload에서 계산하며 IdempotencyKey와 별도 필드로 관리해야 한다. |
| NSL-IDM-005 | 동일 IdempotencyKey + 동일 PayloadHash는 동일 Business Result를 반환해야 한다. |
| NSL-IDM-006 | 동일 IdempotencyKey + 다른 PayloadHash는 IDEMPOTENCY_CONFLICT여야 한다. |
| NSL-IDM-007 | Runtime은 Suspend/Resume에서 동일 BusinessOperationId/WriteNode에 동일 IdempotencyKey를 재사용해야 한다. |
| NSL-IDM-008 | Durable duplicate guarantee는 Canonical Business API/Tool Contract가 제공해야 한다. |

---

# 15. Commit / Reconciliation Requirements

CommitState:

```text
COMMITTED
NOT_COMMITTED
UNKNOWN_COMMIT_STATE
```

| ID | 요구사항 |
|---|---|
| NSL-CMT-001 | WRITE 결과에 CommitState가 있어야 한다. |
| NSL-CMT-002 | UNKNOWN_COMMIT_STATE를 ordinary failure로 변환하지 않아야 한다. |
| NSL-CMT-003 | UNKNOWN_COMMIT_STATE는 RECONCILIATION_REQUIRED로 이어져야 한다. |
| NSL-CMT-004 | Reconciliation 전 동일 업무를 새 Key로 재실행하지 않아야 한다. |

---

# 16. Post-Write Verification Requirements

`CommitState`와 `VerificationStatus`는 독립적으로 유지한다.

권장 `VerificationStatus`:

```text
NOT_REQUESTED
VERIFIED
FAILED
UNKNOWN
```

| ID | 요구사항 |
|---|---|
| NSL-VFY-001 | COMMITTED 결과는 가능한 경우 Business Reference를 반환해야 한다. |
| NSL-VFY-002 | Tool Contract가 Verification 방법을 제공할 수 있어야 한다. |
| NSL-VFY-003 | Verification 실패와 Commit 실패를 구분해야 한다. |
| NSL-VFY-004 | Verification 결과는 typed `VerificationStatus`로 Audit/Result에 포함되어야 한다. |
| NSL-VFY-005 | `commit_state=COMMITTED` 이후 Verification이 FAILED/UNKNOWN이어도 CommitState를 NOT_COMMITTED로 재분류해서는 안 된다. |

---

# 17. ExecutionContext / Checkpoint Requirements

| ID | 요구사항 |
|---|---|
| NSL-CTX-201 | ExecutionContext는 per-execution Approval State를 보존할 수 있어야 한다. |
| NSL-CTX-202 | ExecutionContext는 per-execution Write Journal State를 보존할 수 있어야 한다. |
| NSL-CTX-203 | ExecutionContext는 per-execution Idempotency State를 보존할 수 있어야 한다. |
| NSL-CTX-204 | ExecutionContext는 Checkpoint State를 보존할 수 있어야 한다. |
| NSL-CTX-205 | Approval/Write/Idempotency 객체가 `Store`/`Journal`로 명명되더라도 외부 Persistence Service가 아니라 per-execution mutable state container여야 한다. |
| NSL-CTX-206 | External persistence, Approval Service, Tool Executor, DB/MCP Client, Trace Sink, Trust Verifier는 ExecutionContext에 Service Locator 형태로 포함되어서는 안 되며 Port/Service로 주입되어야 한다. |
| NSL-CTX-207 | Resume 후 Symbol/Check/Resource/Approval/Write/Idempotency 상태를 복원할 수 있어야 한다. |
| NSL-CTX-208 | Checkpoint는 Skill semantic hash와 binding되어야 한다. |
| NSL-CTX-209 | Checkpoint는 `BusinessOperationId`, `ApprovalRequestId`, `write_intent_hash`, `PayloadHash`를 Resume 검증에 필요한 수준으로 보존해야 한다. |
| NSL-CTX-210 | v0.2 ExecutionRequest는 v0.1의 Principal / DataPolicy Security Context를 제거하지 않고 보존해야 한다. |

---

# 18. Execution Status Requirements

v0.2에서 추가되는 durable Runtime 상태:

```text
WAITING_FOR_APPROVAL
RECONCILIATION_REQUIRED
```

v0.1에서 보존해야 하는 상태:

```text
CREATED
RUNNING
COMPLETED
FAILED
TOOL_ERROR
VALIDATION_ERROR
LIMIT_EXCEEDED
CANCELLED
```

다음은 NSL Runtime의 durable `ExecutionStatus`가 아니다.

```text
RESUME_QUEUED
→ Agent/Platform Queue State

WRITE_IN_PROGRESS
→ internal write-attempt state / audit event
```

| ID | 요구사항 |
|---|---|
| NSL-STS-201 | v0.1 ExecutionStatus를 additive하게 보존해야 한다. |
| NSL-STS-202 | `VALIDATION_ERROR`를 v0.2에서도 유지해야 한다. |
| NSL-STS-203 | `RESUME_QUEUED`를 NSL durable ExecutionStatus로 정의해서는 안 된다. |
| NSL-STS-204 | `WRITE_IN_PROGRESS`는 public durable ExecutionStatus가 아니라 internal attempt state 또는 trace/audit event로 모델링해야 한다. |
| NSL-STS-205 | UNKNOWN_COMMIT_STATE는 `RECONCILIATION_REQUIRED` ExecutionStatus/Disposition으로 이어질 수 있어야 한다. |

## 18.1 ExecutionResult Additive Compatibility

v0.2 `ExecutionResult`는 v0.1 Result Contract를 대체하지 않고 additive하게 확장해야 한다.

권장 v0.2 optional fields:

```text
pre_write_eligibility
approval
write
verification
suspension
```

Public field name은 Runtime Python Interface의 canonical `ExecutionResult`와 일치하며, `approval`/`write`/`verification`은 각각 Summary DTO를 담는다.

READ-only IR 1.0 실행에서는 v0.2 WRITE 관련 필드가 `None`/Not Applicable 의미를 가질 수 있어야 한다.

| ID | 요구사항 |
|---|---|
| NSL-RSL-201 | v0.1 ExecutionResult의 기존 validation/evidence/output/resource/error 의미를 보존해야 한다. |
| NSL-RSL-202 | v0.2 WRITE/Approval/Verification 필드는 additive optional field로 확장해야 한다. |
| NSL-RSL-203 | READ-only 실행을 위해 WRITE 관련 필드를 강제로 의미 있는 값으로 채우지 않아야 한다. |

---

# 19. `.nso` IR Requirements

| ID | 요구사항 |
|---|---|
| NSL-IR-201 | IR Version 1.1을 지원해야 한다. |
| NSL-IR-202 | ApprovalStatement Node를 지원해야 한다. |
| NSL-IR-203 | WriteExpression Node를 지원해야 한다. |
| NSL-IR-204 | WRITE Node는 approval_ref를 가져야 한다. |
| NSL-IR-205 | RequiredTool에는 WRITE capability/risk/contract hash가 포함되어야 한다. |
| NSL-IR-206 | Source Language `0.1`은 IR `1.0`, Source Language `0.2`는 IR `1.1`로 deterministic mapping되어야 한다. |
| NSL-IR-207 | Source Language declaration은 authoritative하며 Compiler Option으로 임의 override해서는 안 된다. |
| NSL-IR-208 | v1.0 READ-only IR은 계속 Load할 수 있어야 한다. |
| NSL-IR-209 | Production WRITE Authenticity를 위해 IR 자체에 별도의 중복 Signature 경로를 강제해서는 안 되며 Signed NSP Package Trust Boundary를 재사용해야 한다. |

---

# 20. Signature / Security Requirements

Production WRITE의 Authenticity는 별도 `.nso` embedded signature 체계를 새로 만들기보다 기존 **Signed NSP → Verified Package Trust Boundary**를 재사용한다.

```text
Canonical NSO / Skill Artifact
      ↓
NSP Build / Package Integrity
      ↓
Publisher Signature / Trusted Key
      ↓
Verified Package / Verified Skill Artifact
      ↓
Runtime Preflight
```

| ID | 요구사항 |
|---|---|
| NSL-SIG-001 | Production WRITE Skill은 유효하게 검증된 Signed NSP Package에서 로드되어야 한다. |
| NSL-SIG-002 | Package Integrity와 Publisher Signature는 Canonical package/artifact payload에 대해 검증되어야 한다. |
| NSL-SIG-003 | Trusted Signing Key만 허용해야 한다. |
| NSL-SIG-004 | Package/Artifact integrity가 변경되면 기존 Trust Evidence를 재사용해서는 안 된다. |
| NSL-SIG-005 | Runtime Preflight는 raw SkillObject에 대한 별도 중복 signature path보다 Verified Package/Skill Trust Evidence를 확인해야 한다. |
| NSL-SIG-006 | v0.1 Signed NSP trust boundary와 호환되어야 한다. |

---

# 21. Risk Requirements

권장 Risk Classification:

```text
R0 pure calculation
R1 ordinary read
R2 sensitive read
R3 draft write
R4 business write
R5 final/external transaction
```

Risk Level은 Tool/Skill의 **static classification metadata**다. User/Tenant별 실제 WRITE 허용 여부는 외부 Policy/OA Decision이다.

| ID | 요구사항 |
|---|---|
| NSL-RSK-001 | Tool Contract는 Risk Level을 선언해야 한다. |
| NSL-RSK-002 | Compiler는 Risk metadata의 존재/형식/계약 정합성을 검증하되 User/Tenant entitlement를 결정해서는 안 된다. |
| NSL-RSK-003 | Runtime은 WRITE 실행 전 현재의 외부 PolicyDecision 또는 검증 가능한 Policy Evidence를 확인해야 한다. |
| NSL-RSK-004 | Tenant/User entitlement, MFA, 추가 승인 조건을 Canonical Tool Contract hash의 환경별 policy 값으로 하드코딩해서는 안 된다. |
| NSL-RSK-005 | v0.2 초기 Acceptance는 R3 중심으로 제한할 수 있어야 한다. |

---

# 22. Replay Requirements

| ID | 요구사항 |
|---|---|
| NSL-RPL-201 | Replay에서 Live WRITE Provider 호출을 금지해야 한다. |
| NSL-RPL-202 | Approval/Write/Commit 결과 Snapshot을 재생할 수 있어야 한다. |
| NSL-RPL-203 | Replay 결과는 원 실행의 WRITE Side Effect를 반복 생성하지 않아야 한다. |

---

# 23. Audit Requirements

필수 Event:

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
```

모든 Event는 가능한 범위에서 다음 identity/evidence와 연결되어야 한다.

```text
execution_id
business_operation_id
approval_request_id
node_id
skill_semantic_hash
idempotency_key
payload_hash
write_intent_hash
```

Generic Audit/Event에는 raw WRITE Payload를 기본 복제하지 않고 protected reference / display-safe summary / classification을 사용해야 한다.

---

# 24. CLI Requirements

기존:

```text
nsl check
nsl compile
nsl run
nsl test
```

추가 개발용 명령 후보:

```text
nsl inspect-signature
nsl verify
```

위 명령은 개별 `.nso`에 독립적인 새로운 서명 체계를 뜻하지 않으며, Signed NSP / Package Trust Evidence를 진단하는 용도로 구현할 수 있다.

CLI run의 Production WRITE Approval은 실제 운영 Approval Service 없이 자동 승인해서는 안 된다. Test Mode에서는 Fake Approval/Test Adapter를 사용할 수 있다.

---

# 25. Testing Requirements

v0.1 Regression Suite를 100% 재실행한다.

신규 필수 Test:

```text
write without requires
write using READ tool
write without approval
unused approval
one approval linked to multiple writes
write in foreach
two write nodes
FAIL before write
UNKNOWN before write
approval reject
approval suspend/resume
checkpoint-before-approval-publish
approval request idempotent publish
approval evidence business-operation mismatch
approval intent hash mismatch
approval payload hash mismatch
approval expire
idempotent duplicate
idempotency conflict
business operation id stable across resume
write-time business precondition failure
committed
not committed
unknown commit state
post-write verify success/failure
signed NSP tamper
untrusted package signature
principal/data-policy preserved on resume
replay no-live-write
IR 1.0 backward compatibility
language 0.1 → IR 1.0
language 0.2 → IR 1.1
```

Coverage 목표:

```text
Statement >= 95%
Branch >= 90%
```

Python 검증 baseline:

```text
Python 3.12+
```

v0.2 구현으로 인해 v0.1 verified quality baseline을 하향해서는 안 된다.

---

# 26. Acceptance Vertical Slice

## AC-W01 Voucher Draft

```text
Natural Language Parameter
→ account/project/period READ validation
→ CHECK all PASS
→ APPROVAL REQUEST
→ suspend
→ approve
→ resume
→ FINANCE.CREATE_VOUCHER_DRAFT
→ COMMITTED
→ GET_VOUCHER verification
→ emit voucher_no
```

## AC-W02 Project Draft

```text
duplicate/parent/period/team validation
→ approval
→ PROJECT.CREATE_PROJECT_DRAFT
→ verify
→ emit project_code
```

---

# 27. Backward Compatibility Acceptance

```text
v0.1 source compiles under v0.2
v0.1 language declaration maps to IR 1.0
v0.1 IR 1.0 runs under v0.2 runtime
v0.1 Principal / DataPolicy request context is preserved
v0.1 ExecutionStatus including VALIDATION_ERROR is preserved
v0.1 ExecutionResult remains compatible
v0.1 replay remains deterministic
```

v0.2 Source는 IR 1.1로 deterministic하게 compile되어야 하며, write-less v0.2 source라도 Source Language 0.2를 선언했다면 IR 1.1 mapping을 유지한다.

---

# 27.1 Closure Alignment Trace

본 SRS에 적용한 Unified Change Ledger 항목:

```text
CHG-001  Document authority hierarchy 통일
CHG-002  Python 3.12+ / Coverage 95/90
CHG-003  BusinessOperationId 도입
CHG-004  IdempotencyKey / PayloadHash 분리
CHG-005  ApprovalRequestId + Evidence Binding
CHG-006  Approval Workflow Ownership → Agent/Platform
CHG-007  PreWriteEligibility에서 Reconciliation 제거
CHG-008  ExecutionStatus 정리
CHG-009  Principal / DataPolicy Request Contract 보존
CHG-010  Signed NSP Trust Boundary 재사용
CHG-011  Approval↔WRITE exactly 1:1
CHG-013  Strict Profile Safety Rules immutable
CHG-014  Language Version → IR Version deterministic mapping
CHG-017  TOCTOU / Write-time Business Preconditions
CHG-018  Checkpoint → Approval Publish Crash Consistency
CHG-023  Risk Classification / PolicyDecision 분리
CHG-024  Approval Payload Protected-reference Model
CHG-027  ExecutionContext State-only Terminology
CHG-029  VerificationStatus typed + Commit 분리
CHG-030  ExecutionResult additive compatibility
```

본 문서는 위 Architecture Closure 결정을 **Normative SRS 요구사항**으로 변환한다. Component 상세 Class/Protocol/Schema는 04~12 상세 설계 문서에서 본 요구사항을 구체화한다.

---

# 28. 최종 Acceptance

NSL v0.2는 다음을 만족해야 한다.

> **검증되지 않았거나 불완전하거나 승인되지 않았거나 신뢰되지 않았거나 Business Preconditions가 만족되지 않았거나 Commit 상태가 불확실한 조건에서는 새로운 Business WRITE를 발생시키지 않는다. UNKNOWN_COMMIT_STATE는 자동 Retry가 아니라 Reconciliation으로 전환한다.**
