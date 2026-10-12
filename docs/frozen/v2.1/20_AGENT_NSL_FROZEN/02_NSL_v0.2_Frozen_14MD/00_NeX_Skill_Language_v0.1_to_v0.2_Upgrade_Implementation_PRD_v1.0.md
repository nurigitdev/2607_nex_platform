# NeX Skill Language v0.1 → v0.2 Upgrade Implementation Plan / PRD v1.0

**문서 버전:** v1.0  
**작성일:** 2026-08-23  
**대상:** 현재 동작 중인 NSL v0.1 코드베이스를 NSL v0.2 Controlled Write로 업그레이드  
**주요 독자:** Codex / NSL 개발자 / 리뷰어  
**Language Target:** NSL 0.2  
**IR Target:** NSO 1.1  
**Python Baseline:** 3.12+  
**기본 Profile:** `NSL-0.2-STRICT`  
**Architecture Closure Alignment:** `NSL v0.2 Architecture Consistency Closure and Unified Change Ledger v1.0 — FROZEN`

---

# 1. 문서 목적

본 PRD는 이미 설계·구현·시험·시연이 완료된 NSL v0.1 코드베이스를, 기존 기능을 깨뜨리지 않으면서 NSL v0.2로 단계적으로 업그레이드하기 위한 구현 계획을 정의한다.

NSL v0.1의 중심 실행 모델:

```text
READ
→ CALCULATE / LET
→ CHECK
→ EMIT
```

NSL v0.2의 중심 실행 모델:

```text
READ
→ DERIVE
→ CHECK
→ WRITE ELIGIBILITY
→ APPROVE
→ SUSPEND
→ RESUME
→ WRITE
→ COMMIT 확인
→ POST-WRITE VERIFY
→ EMIT
```

v0.2는 단순히 `write` Keyword를 추가하는 기능 개발이 아니다.

핵심 목표는:

> **부정확하거나 불완전하거나 승인되지 않았거나 위변조되었거나 Commit 상태가 불확실한 상태에서는 실제 Business WRITE가 발생하지 않도록 하는 Controlled Write Runtime을 구축하는 것**

이다.

---

# 2. 문서 Authority / Source of Truth

본 PRD는 **Implementation Plan / Phase / Milestone** 문서다. 구현 순서와 Acceptance를 정의하지만, Cross-Cutting Semantic Architecture나 Normative Requirement를 임의로 재정의하지 않는다.

구현 시작 전 다음 Frozen Decision 문서를 먼저 읽는다.

```text
NSL v0.2 Architecture Consistency Closure and Unified Change Ledger v1.0 — FROZEN
NSL v0.2 Architecture Delta Decision Record v1.0 — FROZEN
NSL v0.2 Batch A — Execution Contract Alignment Decision Record v1.0 — FROZEN
NSL v0.2 Batch B — Compiler Architecture Alignment Decision Record v1.0 — FROZEN
NSL v0.2 Batch C — Runtime Architecture Alignment Decision Record v1.0 — FROZEN
```

## 2.1 Concern별 Authority

```text
MASTER_PROMPT
  → Implementation Process / Safety / Quality Guardrail

Document Baseline & Upgrade Plan
  → Scope / Version / Document Authority

Frozen Architecture Closure / ADR + Controlled Write Architecture
  → Cross-Cutting Semantic Architecture / Responsibility Boundary

SRS
  → Normative Functional / Non-functional Requirements

Component Detailed Design
  → Compiler / IR / Tool / Runtime Implementation Design

Upgrade PRD (본 문서)
  → Implementation Plan / Phase / Milestone
```

문서 간 충돌은 단순한 목록 순서가 아니라 위 **Concern별 Authority**로 해결한다. Frozen Architecture Closure/ADR와 상충하는 의미론 또는 책임 경계 변경이 필요하면 구현 문서를 임의 수정하지 말고 먼저 ADR 개정 여부를 결정한다.

## 2.2 Implementation Baseline Documents

1. `NSL v0.2 Document Baseline & Upgrade Plan v1.0`
2. `NSL v0.2 Controlled Write / Approval / Idempotency Detailed Design v0.1`
3. `NSL v0.2 Interpreter & Runtime SRS v2.0 Draft`
4. `NSL Shared Core / IR Single Source of Truth Detailed Design v0.2`
5. `NSL Object (.nso) IR Schema Detailed Design v0.3` — actual IR `1.1`
6. `NSL Tool Contract Detailed Design v0.2`
7. `NSL Compiler Detailed Design v0.2`
8. `NSL Compiler Python Class / Interface Detailed Design v0.2`
9. `NSL Runtime Validation Semantics Detailed Design v0.2`
10. `NSL Runtime ExecutionContext Detailed Design v0.2`
11. `NSL Runtime Class/Object Model Detailed Design v0.2`
12. `NSL Runtime Python Interface / Protocol Detailed Design v0.2`

기존 v0.1 문서는 Regression Compatibility와 기존 동작 확인용 Reference로 사용한다.

---
# 3. 현재 상태에 대한 전제

현재 NSL v0.1은 다음 기능이 이미 구현되어 있다고 가정한다.

```text
.ns Source
include
true / false

Lexer
Parser
AST

Symbol / Scope
Type Check
Tool Contract Resolution
Safety / Resource Bound

.nso IR 1.0
Hash / Tamper Detection

READ
LET
FOREACH
CHECK
EMIT

PASS / FAIL / UNKNOWN
Partial Data Handling

Runtime
Tool Call
Mock / Replay
CLI check / compile / run / test
```

단, 실제 v0.1 Repository 소스가 본 PRD 작성 시점에 입력으로 제공되지 않았으므로 **Codex는 위 구조를 실제 코드 구조로 간주해서는 안 된다.**

반드시 Phase 0에서 실제 Repository를 조사하고 현재 코드와 설계 문서의 Mapping을 먼저 작성해야 한다.

**Repository 실제 구조가 문서의 예시 Package Tree보다 우선한다.** 이후 문서의 `core/`, `ir/`, `runtime/` 구조는 우선 Logical Responsibility Model로 해석하며, 문서 예시를 맞추기 위한 Big-bang Package Reorganization은 하지 않는다.

---

# 4. 제품 목표

## 4.1 P0 — 반드시 달성

1. 모든 기존 v0.1 `.ns`가 v0.2 Compiler에서 계속 Compile되어야 한다.
2. 모든 기존 IR 1.0 `.nso`가 v0.2 Runtime에서 계속 실행되어야 한다.
3. 기존 v0.1 Regression Test가 모두 통과해야 한다.
4. `write`, `approve`, `approved_by` 문법을 지원해야 한다.
5. Compiler는 WRITE Safety를 정적으로 검증해야 한다.
6. IR 1.1에 `ApprovalStatement`, `WriteExpression`을 생성해야 한다.
7. Runtime은 Approval 요청 시 실행을 Suspend하고 Checkpoint할 수 있어야 한다.
8. Resume 시 승인된 Write Intent와 실제 Payload의 동일성을 검증해야 한다.
9. 모든 WRITE에 Idempotency Key를 사용해야 한다.
10. `FAIL` 또는 `UNKNOWN`이 하나라도 있으면 WRITE를 차단해야 한다.
11. `UNKNOWN_COMMIT_STATE`에서 자동 Retry하지 않아야 한다.
12. Replay/Test는 실제 Live WRITE를 호출하지 않아야 한다.
13. Production WRITE Skill은 Trusted Verified Signed NSP Package 경계를 통해 Authenticity/Trust가 검증되어야 한다.
14. Statement Coverage ≥ 95%, Branch Coverage ≥ 90%를 만족해야 한다.

## 4.2 P1 — 강하게 권장

1. Post-Write Verification 지원
2. Risk Level R0~R5 지원
3. Approval TTL/Expiration 지원
4. `.nso` IR 1.0 / 1.1 Round-trip Test
5. Architecture Dependency Test
6. 전표 Draft Vertical Slice
7. 프로젝트 Draft Vertical Slice

## 4.3 Non-Goal

v0.2에서는 다음을 구현하지 않는다.

```text
UPDATE
DELETE
CANCEL
POST / FINALIZE

General Transaction Language
try / catch
rollback keyword
retry keyword

Skill 내부 LLM 호출
Dynamic WRITE Tool Selection

여러 WRITE Node
FOREACH 내부 WRITE
Bulk WRITE

NeX-AE 자연어 Intent Engine 자체
600개 계정과목 LLM Ranking Engine 자체
```

---

# 5. 대표 Use Case

## UC-W01 — 전표 Draft 생성

입력 예:

```text
account_code
project_code
transaction_date
amount
description
```

실행:

```text
READ ACCOUNT.GET_ACCOUNT
READ PROJECT.GET_PROJECT
READ FINANCE.GET_ACCOUNTING_PERIOD

CHECK ACCOUNT_VALID
CHECK PROJECT_VALID
CHECK PERIOD_OPEN
CHECK AMOUNT_VALID

APPROVE VOUCHER_CREATE

WRITE FINANCE.CREATE_VOUCHER_DRAFT

VERIFY FINANCE.GET_VOUCHER

EMIT voucher_no / status
```

## UC-W02 — 프로젝트 Draft 생성

```text
READ parent project
READ duplicate project

CHECK parent active
CHECK duplicate absent
CHECK period valid
CHECK team authority

APPROVE PROJECT_CREATE

WRITE PROJECT.CREATE_PROJECT_DRAFT

VERIFY PROJECT.GET_PROJECT

EMIT project_code / status
```

---

# 6. Natural Language / 계정과목 처리 경계

약 600개 계정과목 중 후보를 고르는 기능을 NSL Runtime에 넣지 않는다.

권장 경계:

```text
NeX-AE
  ↓
Intent / Entity Extraction
  ↓
ACCOUNT.SEARCH_ACCOUNT_CODES
  ↓
Candidate Ranking
  ↓
Selected account_code
  ↓
NSL Input
  ↓
ACCOUNT.GET_ACCOUNT
  ↓
Deterministic Validation
```

NSL은 **선택 결과의 유효성 검증과 WRITE 실행 안전성**을 담당한다.

---

# 7. 핵심 Safety Invariants

다음 항목은 구현 전 과정에서 깨져서는 안 된다.

```text
INV-001 FAIL → no WRITE
INV-002 UNKNOWN → no WRITE
INV-003 No Approval → no WRITE
INV-004 Approval WriteIntentHash 또는 PayloadHash Mismatch → no WRITE
INV-005 Invalid/Untrusted Verified Package Trust Evidence → no Production WRITE
INV-006 Tool Contract Hash Mismatch → no WRITE
INV-007 Non-WRITE Tool 사용 → Compile/Preflight Reject
INV-008 Non-Atomic WRITE Tool → Compile/Preflight Reject
INV-009 Idempotency 미지원 WRITE Tool → Reject
INV-010 동일 Idempotency Key + 다른 Payload → Reject
INV-011 UNKNOWN_COMMIT_STATE → no automatic retry
INV-012 Replay/Test → no live WRITE
INV-013 WRITE inside FOREACH → Compile Error
INV-014 More than one WRITE → Compile Error
INV-015 v0.1 READ-only Skill Behavior는 변경되지 않음
```

---

# 8. 개발 원칙

Codex는 다음 순서를 지킨다.

```text
1. 기능 추가 전 기존 코드 구조 분석
2. 필요한 경우 Refactoring 먼저
3. 한 번에 큰 Rewrite 금지
4. Phase 단위 Small Change
5. 각 Phase마다 Unit + Regression Test
6. Test 통과 후 다음 Phase
7. Shared core/ir 정의 중복 금지
8. Runtime → Compiler Dependency 금지
9. Compiler → Runtime Dependency 금지
10. Live WRITE가 테스트에서 호출되지 않도록 Guard
```

기존 동작을 보존하는 것이 기능 추가보다 우선한다.

---

# 9. Phase 0 — Repository Reconnaissance / Upgrade Map

## 목표

실제 v0.1 코드와 v0.2 설계 간의 Gap을 확인한다.

## Codex 작업

Repository 전체를 먼저 탐색한다.

작성해야 할 임시 산출물:

```text
docs/upgrade/v0.2/current_architecture.md
docs/upgrade/v0.2/impact_map.md
```

확인 대상:

```text
package tree
core Type 위치
IR Object 위치
Lexer/Parser
AST
Compiler Pass
Tool Contract
RuntimeEngine
ExecutionContext
ExpressionEvaluator
StatementExecutor
Validation
Replay
CLI
Tests
```

## 반드시 찾을 것

```text
중복 Type Model 여부
Compiler / Runtime 간 역방향 Import
IR 1.0 Version 처리 위치
Hash 계산 위치
Tool Call abstraction
Mock/Replay abstraction
CLI entrypoint
Test fixture 위치
Coverage 설정
```

## 금지

Phase 0에서는 동작 변경을 하지 않는다.

## Acceptance

- 현재 Package Map 작성
- v0.2 변경 대상 파일 목록 작성
- Refactoring 선행 필요 여부 결정
- 기존 전체 Test 실행 결과 Baseline 기록
- 현재 Coverage 기록

---

# 10. Phase 1 — Architecture Guard / v0.1 Baseline Lock

## 목표

v0.2 변경 전에 v0.1 동작을 고정한다.

## 작업

1. 기존 Regression Test 전체 실행
2. 빠진 핵심 v0.1 Golden Test 보완
3. Architecture Dependency Test 추가
4. v0.1 `.ns → compile → .nso → run` Golden Fixture 고정
5. IR 1.0 Fixture 고정

## 신규 Test

```text
test_v01_source_compile_golden
test_v01_ir10_decode
test_v01_runtime_golden
test_v01_replay_golden
test_no_compiler_runtime_cycle
test_core_single_source_of_truth
```

## Acceptance

기존 v0.1 Behavior Snapshot이 확정되고 이후 모든 Phase에서 Regression Gate로 사용된다.

---

# 11. Phase 2 — Shared Core 확장

## 목표

WRITE/Approval에 필요한 공통 Value Model을 추가한다.

## Logical Responsibility 예시

아래 구조는 구현 책임을 설명하기 위한 예시이며, 실제 v0.1 Repository의 물리 Package를 강제하지 않는다.

```text
nsl/core/
  approvals.py
  writes.py
  risks.py
```

## 추가 Model

```python
ApprovalStatus
PreWriteEligibility
CommitState
VerificationStatus
RiskLevel
BusinessOperationId
ApprovalRequestId
IdempotencyKey
PayloadHash
```

`BusinessOperationId`, `ApprovalRequestId`, `IdempotencyKey`, `PayloadHash`는 Runtime execution identity/evidence를 표현하는 shared value type이며, Compiler/IR이 runtime instance 값을 생성한다는 의미가 아니다.

기존:

```text
TypeInfo
Money
Presence
Completeness
CheckStatus
ValueEnvelope
```

는 변경을 최소화한다.

## 금지

```text
ApprovalStore
WriteJournal
CheckpointRepository
WriteExecutor
```

를 `core/`에 넣지 않는다.

## Acceptance

Compiler와 Runtime이 동일 Core Definition을 사용한다.

---

# 12. Phase 3 — IR 1.1 Object Model

## 목표

IR 1.0을 깨뜨리지 않고 Approval/WRITE Node를 추가한다.

## 추가 Object

```text
ApprovalStatement
WriteExpression
ApprovalPolicy
```

Package signature/trust metadata는 canonical semantic IR object로 추가하지 않는다. Production WRITE trust는 Signed NSP Package Boundary에서 생성된 `Verified Package / Skill Trust Evidence`를 Runtime이 소비한다.

## RequiredTool 확장

```text
risk_level
WRITE capability
```

## StaticAnalysis 확장

```text
write_node_count
approval_node_count
max_write_calls
writes_inside_loop
all_writes_approved
requires_verified_package_for_write
```

## Codec

IR 1.0 / 1.1 모두 Decode 가능해야 한다.

## Test

```text
IR 1.0 decode
IR 1.1 decode
IR 1.1 encode/decode round-trip
ApprovalStatement canonical JSON
WriteExpression canonical JSON
deterministic semantic hash
unknown IR version reject
```

## Acceptance

IR 1.1 Object가 Compiler/Runtime 양쪽의 단일 실행 Contract가 된다.

---

# 13. Phase 4 — Tool Contract v0.2

## 목표

READ Tool과 WRITE Tool의 실행 의미를 분리한다.

## 추가 Contract Field

```text
capability
operation_kind
risk_level
write_semantics.side_effect
write_semantics.atomicity
write_semantics.idempotency.required
write_semantics.idempotency.scope
write_semantics.idempotency.duplicate_behavior
write_semantics.commit.confirmation
write_semantics.approval.required
write_semantics.verification.tool_id
```

## Tool Error 추가

```text
APPROVAL_REQUIRED
APPROVAL_INVALID
IDEMPOTENCY_CONFLICT
WRITE_POLICY_DENIED
ATOMICITY_NOT_SUPPORTED
UNKNOWN_COMMIT_STATE
POST_WRITE_VERIFICATION_FAILED
BUSINESS_CONFLICT
```

## Mock Contract

최소 다음 Contract Fixture 작성:

```text
ACCOUNT.GET_ACCOUNT             READ
PROJECT.GET_PROJECT             READ
FINANCE.GET_ACCOUNTING_PERIOD   READ
FINANCE.CREATE_VOUCHER_DRAFT    WRITE / CREATE_DRAFT / R3
PROJECT.CREATE_PROJECT_DRAFT    WRITE / CREATE_DRAFT / R3
```

## Acceptance

WRITE Tool이 atomic/idempotent/approval-enabled가 아니면 Compiler 또는 Runtime에서 거부 가능해야 한다.

---

# 14. Phase 5 — Compiler Syntax / AST

## 목표

`write`, `approve`, `approved_by`를 Language 0.2에 추가한다.

## Lexer

Reserved Keyword:

```text
write
approve
approved_by
```

## AST

```python
ApproveStatementAst
WriteExpressionAst
```

## Parser

지원:

```nsl
approve ID {
    message "...";
}

let x =
    write TOOL(...)
    approved_by ID;
```

## Acceptance

Syntax만으로 v0.2 Source를 안정적으로 Parse할 수 있다.

---

# 15. Phase 6 — Compiler Semantic / Write Safety

## 목표

WRITE 안전성을 Runtime 전에 최대한 정적으로 증명한다.

## Approval Namespace

기존 Symbol Namespace에 Approval을 추가한다.

## WriteSafetyAnalyzer

신규 Service 권장:

```python
class WriteSafetyAnalyzer:
    def analyze(...) -> WriteSafetyAnalysis:
        ...
```

## Safety Profile Rule

`WRITE count <= 1`, `WRITE not in FOREACH` 등 Safety-critical 제한은 일반 Compiler Option으로 임의 완화할 수 없다. `NSL-0.2-STRICT` Semantics Profile의 immutable rule로 적용한다. Test/Demo에서도 Safety Rule을 우회하는 Option을 만들지 않는다.

## 필수 검사

```text
WRITE count <= 1
WRITE not in FOREACH
approval exists
approval occurs before write
tool capability == WRITE
operation kind supported
atomicity == ATOMIC
idempotency required
risk declared
dynamic WRITE tool forbidden
```

## Type Checker

WRITE Argument/Result Type을 Tool Contract와 검증한다.

## Diagnostic

```text
NSL-E5201 WRITE_IN_FOREACH
NSL-E5202 TOO_MANY_WRITES
NSL-E5301 UNKNOWN_APPROVAL
NSL-E5302 APPROVAL_ORDER
NSL-E5401 WRITE_CAPABILITY_REQUIRED
NSL-E5402 WRITE_ATOMICITY_REQUIRED
NSL-E5403 IDEMPOTENCY_REQUIRED
```

## Acceptance

잘못된 WRITE Skill은 `.nso` 생성 전에 거부된다.

---

# 16. Phase 7 — Compiler Lowering / IR 1.1

## 목표

v0.2 AST를 Canonical IR 1.1로 Lowering한다.

## Mapping

```text
ApproveStatementAst → ApprovalStatement
WriteExpressionAst → WriteExpression
```

## Deterministic ID

```text
approval0001
write0001
```

## Analysis Metadata

```text
write_node_count
approval_node_count
max_write_calls
writes_inside_loop
all_writes_approved
requires_verified_package_for_write
```

## Acceptance

동일 Source + 동일 Contract는 동일 Canonical IR / Semantic Hash를 생성한다.

---

# 17. Phase 8 — Validation Semantics / PreWriteEligibility

## 목표

기존 CHECK 결과와 WRITE 허용 상태를 분리한다.

## 기존 유지

```text
PASS
FAIL
UNKNOWN
```

## 신규

```text
PreWriteEligibility:
ALLOWED
BLOCKED
REQUIRES_APPROVAL
```

`RECONCILIATION_REQUIRED`는 pre-write eligibility가 아니라 `UNKNOWN_COMMIT_STATE` 이후의 Runtime `ExecutionStatus / Disposition`이다.

## Rule

```text
FAIL → BLOCKED
UNKNOWN → BLOCKED
ALL PASS + approval pending → REQUIRES_APPROVAL
ALL PASS + approved + policy/preflight pass → ALLOWED
```

Approval은 FAIL/UNKNOWN을 Override할 수 없다.

## Acceptance

`UNKNOWN → WRITE` 경로가 코드 구조상 존재하지 않는다.

---

# 18. Phase 9 — ExecutionContext v0.2

## 목표

Suspend/Resume과 WRITE 상태를 안전하게 보존한다.

## 추가 상태

```text
ApprovalStore
WriteJournal
IdempotencyState
CheckpointState
```

## 추가 Execution Status

```text
WAITING_FOR_APPROVAL
RECONCILIATION_REQUIRED
```

`RESUME_QUEUED`는 Agent/Platform Queue State이며 NSL durable `ExecutionStatus`가 아니다. `WRITE_IN_PROGRESS`는 public durable status가 아니라 internal write-attempt state 또는 trace/audit event로 모델링한다.

## 추가 DTO

```text
ApprovalRecord
WriteIntent
WriteJournalEntry
ExecutionCheckpoint
```

## Acceptance

Context Snapshot → Restore 후 필요한 Runtime State가 동일하게 복원된다.

---

# 19. Phase 10 — Approval Suspend / Resume

## 목표

Worker가 승인 대기 중 Blocking되지 않도록 한다.

## NSL / Platform Responsibility Boundary

NSL Runtime은 Approval **semantics와 evidence contract**를 담당한다. 승인자 Routing, UI/Notification, Approval persistence, Approval Event 수신, Resume Job enqueue/scheduling은 Agent/NeX Platform Control Plane이 담당한다.

NSL Runtime 측 Port/Service는 외부 workflow를 소유하지 않고 Approval Request를 발행하고 Resume 시 Approval Evidence를 검증할 수 있는 경계로 제한한다.

```text
ApprovalRequestPort / ApprovalPort   # request publish boundary
ApprovalEvidence validation         # resume-time validation
CheckpointPort                      # runtime checkpoint persistence boundary
CheckpointCoordinator               # local state serialization/restore
```

`ApprovalCoordinator`라는 이름을 사용하더라도 역할은 **Approval Request 생성/발행과 evidence validation 보조**로 제한하며, Human workflow orchestration을 포함하지 않는다.

## NEW Flow

```text
NSL execute
→ approval gate
→ WriteIntent Freeze
→ PayloadHash / write_intent_hash 확정
→ ApprovalRequestId 생성
→ Checkpoint Save
→ Approval Request Publish
→ WAITING_FOR_APPROVAL
→ return

Agent / NeX Platform
→ Approval Routing / UI / Decision
→ Resume Job enqueue
```

## RESUME Flow

```text
Platform Resume Request
→ checkpoint load
→ skill semantic hash 확인
→ approval evidence/token 확인
→ intent hash 재검증
→ context restore
→ continue
```

## Test

```text
approval pending suspend
approval approved resume
approval rejected
approval expired
approval token tamper
write intent mismatch
checkpoint semantic hash mismatch
```

## Acceptance

Approval 대기를 위한 장시간 Worker Blocking이 없다.

---

# 20. Phase 11 — WRITE Port / Idempotency / Commit State

## 목표

READ와 Side Effect 실행 경계를 코드 수준에서 분리한다.

## Port

```python
WriteExecutionPort
```

## Request

```text
WriteCallRequest
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
business_precondition_evidence
call_context
```

## Outcome Algebra

```text
WriteCommitted
WriteNotCommitted
WriteCommitUnknown
```

## IdempotencyKeyFactory

`Tenant/Idempotency Scope + BusinessOperationId + WriteNodeId`에서 stable Key를 생성한다. `PayloadHash`는 Key 생성 입력과 분리하여 동일 Key + 다른 Payload conflict를 검출할 수 있어야 한다.

## Durable WRITE_REQUESTED

Provider 호출 전에 `BusinessOperationId`, `IdempotencyKey`, `PayloadHash`, `ToolInvocationId`를 durable `WRITE_REQUESTED` evidence로 기록한다. Durable record 성공 이전에는 Provider WRITE를 호출하지 않는다.

## Acceptance

`UNKNOWN_COMMIT_STATE`가 일반 ToolFailure로 축소되지 않으며, Provider 호출 전 durable `WRITE_REQUESTED` 경로가 존재한다.

---

# 21. Phase 12 — WriteGuard / RuntimePreflight

## 목표

실제 Provider 호출 직전 마지막 Safety Gate를 구현한다.

## WriteGuard 검사

```text
Validation ALL PASS
Approval Evidence VALID
BusinessOperationId / ApprovalRequestId Binding Match
WriteIntentHash Match
PayloadHash Match
Current PolicyDecision Allow
Write-time Business Preconditions Pass
Idempotency Request State Valid
Not Live Replay
```

## RuntimePreflight 검사

```text
IR version
feature support
Verified Package / Skill Trust Evidence valid
write enabled
RequiredTool capability WRITE
tool contract hash match
Atomicity ATOMIC
Idempotency Supported
required port availability
```

## Acceptance

어떤 단일 Safety 조건 실패도 Provider WRITE 호출 전 차단한다.

---

# 22. Phase 13 — Signed NSP Trust / Authenticity

## 목표

v0.1에서 이미 구현된 Signed NSP Package Trust Boundary를 재사용하여 Production WRITE의 Authenticity를 보장한다.

## Trust Flow

```text
Canonical SkillObject / NSO
→ NSP Build
→ Package Sign
→ NspVerifier
→ Verified Package / Trust Evidence
→ RuntimePreflight
→ Production WRITE
```

## 원칙

```text
Compiler Core 안에 Private Key 저장 금지
직접 Crypto Algorithm 구현 금지
NSO 개별 Signature Layer를 중복 도입하지 않음
Production WRITE는 Trusted Verified Signed NSP Package에서 로드된 Skill만 허용
semantic/package change는 기존 Trust Evidence를 무효화해야 함
```

실제 Crypto Provider/Library와 Trust Store 정책은 기존 v0.1 Package Verification 구현과 Repository Dependency 정책을 우선 재사용한다.

## Acceptance

Production Profile의 WRITE Skill은 유효한 Verified Signed NSP Trust Evidence 없이는 실행되지 않는다.

---
# 23. Phase 14 — Post-Write Verification

## 목표

COMMITTED 응답 이후 실제 Business Object 존재 여부를 확인한다.

예:

```text
CREATE_VOUCHER_DRAFT
→ voucher_no
GET_VOUCHER(voucher_no)
→ verify
```

## 결과 분리

```text
CommitState
VerificationStatus
```

Verification 실패를 Commit 실패로 해석하지 않는다.

## Acceptance

WRITE Result에는 Commit과 Verification 상태가 각각 명확하게 표현된다.

---

# 24. Phase 15 — Replay / Mock Safety

## 목표

v0.2 테스트와 Replay에서 Side Effect를 완전히 차단한다.

## 구현

```text
MockWriteExecutor
ReplayWriteExecutor
MockApprovalPort
MemoryCheckpointPort
FakePackageTrustEvidence / VerifiedSkillArtifactFixture
FakeRuntimePolicyPort
```

## Hard Guard

Replay Mode에서 Live Write Port 주입 자체를 금지하거나 RuntimePreflight에서 Reject한다.

## Acceptance

Regression/Replay/Test 중 실제 ERP/API WRITE가 발생할 수 있는 코드 경로가 없다.

---

# 25. Phase 16 — Vertical Slice 1: Voucher Draft

## 목표

NSL v0.2 전체 Architecture를 하나의 Use Case로 연결한다.

## 준비 Tool

```text
ACCOUNT.GET_ACCOUNT
PROJECT.GET_PROJECT
FINANCE.GET_ACCOUNTING_PERIOD
FINANCE.CREATE_VOUCHER_DRAFT
FINANCE.GET_VOUCHER
```

## Test Scenarios

```text
happy path
account invalid
project invalid
period closed
amount invalid
partial read → UNKNOWN
approval reject
approval expire
idempotent resume
unknown commit
verification failure
```

## Acceptance

Mock Canonical Tool 환경에서 E2E Controlled Write가 동작한다.

---

# 26. Phase 17 — Vertical Slice 2: Project Draft

Tool:

```text
PROJECT.GET_PROJECT
PROJECT.CHECK_DUPLICATE
PROJECT.CREATE_PROJECT_DRAFT
```

Validation:

```text
parent active
duplicate absent
date range valid
team authority
```

Voucher와 다른 업무에서도 동일 Runtime WRITE Architecture가 재사용됨을 검증한다.

---

# 27. Phase 18 — CLI / Developer Experience

기존 명령:

```text
nsl check
nsl compile
nsl run
nsl test
```

를 유지한다.

추가 후보:

```text
nsl verify
nsl inspect-signature
```

Production Approval Flow를 CLI 자동승인으로 구현하지 않는다.

Local Test/Demo에서는 명시적인 FakeApprovalPort/Test Harness를 사용한다.

## Acceptance

v0.1 CLI 사용법이 깨지지 않는다.

---

# 28. Phase 19 — Full Regression / Quality Gate

## 전체 Test

```text
v0.1 Unit
v0.1 Regression
v0.1 Golden

v0.2 Lexer/Parser
v0.2 Compiler Semantic
v0.2 IR
v0.2 Approval
v0.2 Checkpoint
v0.2 Idempotency
v0.2 Commit
v0.2 Package Trust
v0.2 Replay
v0.2 Vertical Slice
Architecture Tests
```

## Coverage

```text
Statement Coverage >= 95%
Branch Coverage >= 90%
```

## Test Design

각 신규 Public Method/Branch에 대해:

```text
Boundary Value
Robustness
Worst Case
Negative Path
State Transition
```

을 적용한다.

## Gate

모든 Test와 Coverage를 통과하지 않으면 v0.2 완료로 간주하지 않는다.

---

# 29. 권장 Test Directory

실제 v0.1 Repository 구조를 우선하되, 신규 테스트를 논리적으로 다음과 같이 구분하는 것을 권장한다.

```text
tests/
├─ core/
├─ ir/
├─ compiler/
│  ├─ syntax/
│  ├─ semantic/
│  └─ write_safety/
├─ tools/
├─ validation/
├─ runtime/
│  ├─ approvals/
│  ├─ checkpoints/
│  ├─ writes/
│  └─ verification/
├─ replay/
├─ vertical/
└─ architecture/
```

---

# 30. Backward Compatibility Matrix

| 입력/기능 | v0.2 Compiler | v0.2 Runtime | 목표 |
|---|---:|---:|---|
| v0.1 `.ns` | 지원 | - | MUST |
| v0.1 IR 1.0 `.nso` | - | 지원 | MUST |
| v0.1 READ Skill | 지원 | 지원 | Behavior 동일 |
| v0.2 `.ns` READ-only | 지원 | 지원 | MUST |
| v0.2 `.ns` WRITE | 지원 | 지원 | MUST |
| IR 1.1 WRITE | - | 지원 | MUST |
| IR 1.1을 v0.1 Runtime에서 실행 | - | 비지원 | 정상 Reject |

---

# 31. Database / Persistence Scope

NSL Runtime Core는 PostgreSQL에 직접 의존하지 않는다.

Core Interface:

```text
CheckpointPort
ApprovalPort
WriteEvidencePort
TraceSink
ProvenanceStore
```

`WriteEvidencePort`는 Provider 호출 전 durable `WRITE_REQUESTED`와 이후 outcome evidence를 보존하는 logical durability contract다. 물리 저장소는 Checkpoint/Event Repository와 공유할 수 있다.

실제 NeX-AE 연결 전 단계에서는:

```text
MemoryCheckpointPort
MemoryWriteEvidencePort
Test Approval Port
Mock/Replay Write Port
```

로 기능을 검증할 수 있다.

Production PostgreSQL JobQueue/Approval Persistence와 Approval workflow orchestration은 NeX-AE/Platform Integration 단계에서 Adapter/Service로 연결한다. NSL Runtime Core는 승인자 Routing, UI, Notification, Resume enqueue를 소유하지 않는다.

---

# 32. NeX-AE Integration은 본 PRD의 핵심 Scope가 아님

본 PRD는 NSL v0.2 자체 업그레이드에 집중한다.

NeX-AE/Platform은 향후:

```text
Natural Language
→ Skill Selection
→ Parameter Extraction
→ Job enqueue
→ Runtime
→ Approval Request 수신
→ Approval Routing / UI / Notification / Decision Persistence
→ Resume enqueue
→ Result Rendering / Reconciliation Orchestration
```

으로 연결한다.

NSL Runtime은 Approval Request/Evidence 및 Checkpoint/Resume 계약을 제공하지만, Approval workflow와 Resume scheduling 자체를 구현하지 않는다.

---

# 33. Codex 작업 방식

## 33.1 수정 전

```text
현재 코드 읽기
관련 Test 읽기
관련 설계문서 확인
Dependency 확인
```

## 33.2 코드 구조

기능을 추가하기 전에 기존 구조가 v0.2 확장을 감당할 수 없는 경우 먼저 Refactoring한다.

문서의 예시 Package/Module 구조를 맞추기 위한 재배치는 하지 않는다. 실제 Repository의 결합도·복잡도·테스트 경계를 기준으로 필요한 Hotspot만 behavior-preserving refactor한다.

Refactoring Commit과 Feature Commit을 가능하면 분리한다.

## 33.3 Phase 완료 조건

각 Phase는:

```text
implementation
unit tests
regression tests
coverage
lint/type check(if configured)
```

을 통과해야 한다.

## 33.4 금지

```text
기존 Test 삭제로 실패 회피
Coverage exclude 남용
Mock에서 Safety Rule 우회
Replay에서 Live WRITE 호출
Compiler/Runtime Type 중복 생성
Unknown Commit 자동 Retry
```

---

# 34. 권장 Commit Milestone

Repository 정책이 허용하는 경우 다음과 같이 작게 나누는 것을 권장한다.

```text
M0 baseline + architecture tests
M1 shared core v0.2
M2 IR 1.1
M3 tool contract v0.2
M4 parser/AST v0.2
M5 compiler write safety
M6 validation/write eligibility
M7 execution context/checkpoint
M8 approval suspend/resume
M9 write/idempotency/commit
M10 signed NSP trust/preflight
M11 verification/replay
M12 voucher vertical slice
M13 project vertical slice
M14 full regression
```

각 Milestone은 Regression Pass 이후에만 다음 단계로 진행한다.

---

# 35. 구현 우선순위

## P0

```text
Backward Compatibility
Core / IR 1.1
Compiler Write Safety
Validation / PreWriteEligibility
Approval Suspend/Resume
Idempotency
Commit State
Mock/Replay Safety
Voucher Draft Vertical Slice
```

## P1

```text
Signed NSP Trust / Production Verification
Post-write Verification
Risk Policy Adapter
Project Draft Vertical Slice
CLI Verify UX
```

단, Production WRITE Release에는 Signed NSP Package Trust 검증 경로가 완료되어야 한다.

---

# 36. Definition of Done

NSL v0.2 구현 완료 조건:

1. 기존 v0.1 Test가 모두 통과한다.
2. v0.1 `.ns`가 v0.2 Compiler에서 동작한다.
3. IR 1.0을 v0.2 Runtime이 실행한다.
4. IR 1.1 Approval/Write를 Compile/Load할 수 있다.
5. WRITE 없는 Approval 또는 Approval 없는 WRITE가 거부된다.
6. Skill당 WRITE > 1이 Compile Error다.
7. FOREACH 내부 WRITE가 Compile Error다.
8. FAIL/UNKNOWN에서 WRITE Provider 호출 횟수가 0이다.
9. Approval Pending에서 Checkpoint 저장 후 `StatementSuspended`를 반환하고 Worker를 release한다.
10. Resume 시 `BusinessOperationId`, `ApprovalRequestId`, `write_intent_hash`, `PayloadHash` binding이 검증된다.
11. 동일 Tenant/Scope + BusinessOperationId + WriteNode의 Resume/Re-execution에서 동일 Idempotency Domain을 유지하며, 동일 Key + 다른 PayloadHash는 conflict다.
12. Provider 호출 전에 durable `WRITE_REQUESTED` evidence가 기록된다.
13. UNKNOWN Commit 상태에서 자동 Retry가 없다.
14. Replay/Test가 Live control-plane decision 또는 Live WRITE를 발생시키지 않는다.
15. Production WRITE가 Trusted Verified Signed NSP Package 경계에서만 허용된다.
16. Voucher Draft Vertical Slice가 통과한다.
17. Project Draft Vertical Slice가 통과한다.
18. Statement Coverage ≥ 95%, Branch Coverage ≥ 90%.
19. Architecture Dependency Test가 통과한다.
20. 문서와 실제 Public Interface가 일치한다.

---

# 37. 최종 구현 Architecture

```text
                   NSL v0.2 Source
                         │
                         ▼
                  ┌──────────────┐
                  │   Compiler   │
                  │              │
                  │ Syntax       │
                  │ Type         │
                  │ Tool         │
                  │ Write Safety │
                  └──────┬───────┘
                         │
                         ▼
                    NSO IR 1.1
                         │
                         ▼
                ┌─────────────────┐
                │ RuntimePreflight│
                └────────┬────────┘
                         │
                         ▼
                 READ / CHECK
                         │
                         ▼
                 PreWriteEligibility
                         │
                  ┌──────┴───────┐
                  │              │
               BLOCKED       APPROVAL
                                 │
                              suspend
                                 │
                              resume
                                 │
                         WriteIntent Hash
                                 │
                            WriteGuard
                                 │
                           Idempotency
                                 │
                                WRITE
                                 │
                       ┌─────────┼─────────┐
                       │         │         │
                  COMMITTED   NOT       UNKNOWN
                             COMMITTED    COMMIT
                       │                   │
                     VERIFY          RECONCILIATION
                       │
                      EMIT
```

---


# 38. Architecture Closure Alignment Trace

본 정렬본은 `NSL v0.2 Architecture Consistency Closure and Unified Change Ledger v1.0 — FROZEN`의 다음 Change를 반영한다.

| Change ID | 본 PRD 반영 내용 |
|---|---|
| CHG-001 | 문서 Authority를 Concern별로 분리하고 PRD를 Implementation Plan으로 위치시킴 |
| CHG-002 | Python Baseline 3.12+, Statement 95% / Branch 90% Quality Gate로 통일 |
| CHG-003 | `BusinessOperationId`를 Runtime business WRITE의 stable identity로 구현 계획에 반영 |
| CHG-004 | `IdempotencyKey`와 `PayloadHash`를 분리하고 same-key/different-payload conflict 경로를 반영 |
| CHG-005 | 정적 `ApprovalId`와 실행 instance `ApprovalRequestId`를 분리하고 evidence binding을 반영 |
| CHG-006 | Approval routing/UI/persistence/resume enqueue ownership을 Agent/Platform으로 고정 |
| CHG-007 | `PreWriteEligibility={BLOCKED,REQUIRES_APPROVAL,ALLOWED}`로 고정하고 Reconciliation을 post-write로 분리 |
| CHG-008 | `RESUME_QUEUED`를 Platform queue state, `WRITE_IN_PROGRESS`를 internal attempt/event로 분리 |
| CHG-010 | per-NSO signer/verifier 경로 대신 Signed NSP → Verified Package/Skill Trust Evidence를 사용 |
| CHG-013 | WRITE 수/FOREACH WRITE 등의 Safety Rule을 `NSL-0.2-STRICT` immutable profile rule로 고정 |
| CHG-017 | WRITE 직전 current business precondition/TOCTOU 방어를 WriteGuard에 반영 |
| CHG-018 | durable Checkpoint 이후 `ApprovalRequestId` 기반 Approval Request publish 순서를 반영 |
| CHG-019 | Provider 호출 전 durable `WRITE_REQUESTED` evidence 기록을 구현 Phase/DoD에 반영 |
| CHG-021 | RuntimePreflight와 WriteGuard의 artifact/static vs current-state 책임을 분리 |
| CHG-023 | Risk classification과 current `PolicyDecision`을 분리 |
| CHG-025 | Replay에서 live Approval/Policy/Trust decision 및 live WRITE 호출 금지 |
| CHG-030 | v0.1 Result contract를 유지하면서 v0.2 fields를 additive하게 확장 |
| CHG-032 | 문서 예시 Package보다 실제 Repository 구조를 우선하고 Big-bang physical reorganization 금지 |

추가로 Production WRITE Authenticity 표현은 Closure의 Signed NSP Trust Boundary와 일치하도록 기존 v0.1 Verified Package 경계 재사용 표현으로 정규화하였다.

---

# 39. 최종 메시지

NSL v0.2의 구현 성공 기준은 단순히 다음 코드가 실행되는 것이 아니다.

```nsl
write FINANCE.CREATE_VOUCHER_DRAFT(...)
```

성공 기준은:

> **WRITE 이전의 모든 검증, Approval, Artifact Authenticity, Tool Contract, Risk, Idempotency가 만족되고, WRITE 이후 Commit과 Verification 상태까지 추적할 수 있으며, 불확실한 상태에서 자동으로 재실행하지 않는 Runtime을 구현하는 것**

이다.

이 PRD를 Codex의 NSL v0.1 → v0.2 Upgrade 구현 기준 문서로 사용한다.
