# NSL v0.2 Document Baseline & Upgrade Plan v1.0

**문서 버전:** v1.0  
**상태:** Implementation Upgrade Baseline — Closure Aligned  
**작성일:** 2026-08-23  
**대상:** NSL v0.1 → NSL v0.2 업그레이드  
**Architecture Closure 기준:** `NSL v0.2 Architecture Consistency Closure and Unified Change Ledger v1.0 — FROZEN`

---

# 1. 목적

본 문서는 NSL v0.1의 설계·구현·시험·시연 완료 상태를 기준으로, NSL v0.2의 **Scope / Version / Document Authority Baseline**과 문서 갱신 순서를 고정한다.

본 문서는 구현 세부 Class/Protocol을 직접 규정하는 문서가 아니다. 문서 간 충돌 시 역할 기반 Authority는 다음과 같이 적용한다.

```text
MASTER_PROMPT
  = Implementation Process / Guardrail

Document Baseline & Upgrade Plan (본 문서)
  = Scope / Version / Document Authority

Architecture Delta ADR / Controlled Write Architecture
  = Cross-cutting Semantic Architecture

SRS
  = Normative Requirements

Component Detailed Designs
  = Compiler / IR / Tool / Runtime 구현 설계

Upgrade PRD
  = Implementation Plan / Phase / Milestone
```

Architecture Closure에서 FROZEN된 결정과 충돌하는 경우에는 개별 문서가 독자적으로 의미를 변경하지 않고, 먼저 Closure ADR의 명시적 개정을 거쳐야 한다.

NSL v0.1의 핵심 범위:

```text
READ
→ CALCULATE / LET
→ CHECK
→ EMIT

+ Bounded Execution
+ .nso Integrity Hash
+ Include
+ Bool true/false
```

NSL v0.2의 핵심 Theme:

> **Controlled Write**

```text
READ
→ DERIVE / CHECK
→ APPROVAL
→ CONTROLLED WRITE
→ POST-WRITE VERIFY
→ EMIT
```

---

# 2. v0.2 핵심 Use Case

대표 Use Case:

1. 자연어 기반 전표 등록
2. 자연어 기반 프로젝트 등록

특히 회계 전표의 경우 약 600개 계정과목 중 적합한 계정과목을 결정해야 하지만, 계정과목 후보 검색/랭킹 자체를 NSL 문법으로 확장하지 않는다.

```text
Natural Language
      ↓
NeX-AE Intent / Candidate Selection
      ↓
Canonical Account Search / Business API
      ↓
Final Candidate Parameters
      ↓
NSL Validation
      ↓
Approval
      ↓
WRITE
```

NSL Runtime 내부에서는 LLM을 호출하지 않는다.

---

# 3. NSL v0.2 Language Scope

v0.1 기능은 모두 유지한다.

추가:

```text
WRITE
APPROVE
approved_by linkage
```

초기 v0.2 Strict Profile의 범위:

```text
READ                   O
CREATE / CREATE_DRAFT   O
APPROVAL                O

UPDATE                  X
DELETE                  X
CANCEL                  X
POST/FINALIZE           X (초기 Baseline)
ROLLBACK LANGUAGE       X
RETRY LANGUAGE          X
```

Database Transaction / Rollback은 Canonical Business API가 책임진다.

---

# 4. v0.2 Strict Safety Baseline

`NSL-0.2-STRICT`는 다음을 강제한다.

```text
1. 모든 WRITE Tool은 requires에 명시되어야 한다.
2. WRITE Tool은 Canonical Tool Contract의 WRITE Capability를 가져야 한다.
3. 모든 WRITE는 명시적 APPROVE Gate와 정적으로 **exactly 1:1**로 연결되어야 한다.
4. CHECK FAIL 또는 UNKNOWN 상태에서 WRITE할 수 없다.
5. 승인 시점의 Write Intent와 실제 Write Payload가 동일해야 한다.
6. WRITE에는 Idempotency Key가 반드시 존재해야 한다.
7. WRITE Tool Contract는 Atomicity와 Commit Semantics를 선언해야 한다.
8. v0.2에서는 Skill당 최대 1개의 WRITE Node를 허용한다.
9. WRITE는 FOREACH 내부에 존재할 수 없다.
10. Replay에서는 실제 WRITE Provider를 호출하지 않는다.
11. Production WRITE는 **신뢰 가능한 Signed NSP Package에서 검증된 Skill**만 실행할 수 있어야 한다.
12. UNKNOWN_COMMIT_STATE에서는 자동 Retry하지 않는다.
```

---

# 5. Approval 기본 Semantics

Source 예:

```nsl
approve VOUCHER_CREATE {
    message "전표를 등록하시겠습니까?";
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

Approval은 단순 UI 이벤트가 아니지만, **Approval Workflow Orchestration 자체는 NSL Runtime의 책임이 아니다.**

```text
NSL Runtime
  Write Intent Freeze
      ↓
  Canonical Payload / Payload Hash
      ↓
  write_intent_hash
      ↓
  Approval Request 생성
      ↓
  Checkpoint Persist
      ↓
  WAITING_FOR_APPROVAL
      ↓
  Worker 종료

---------------- Platform Control Plane ----------------

Agent / Approval Platform
  Approval Routing / UI / Notification
      ↓
  Human Decision
      ↓
  Resume Job Scheduling / Enqueue

---------------- NSL Resume Boundary ----------------

NSL Runtime
  Approval Evidence 검증
      ↓
  Write Intent / Payload Hash 재검증
      ↓
  WRITE
```

NSL은 Approval Request와 Approval Evidence의 의미론 및 검증을 담당하고, 승인자 선택·UI·알림·Approval Persistence·Resume Queue 생성은 Agent/Platform이 담당한다.

---

# 6. Idempotency 기본 Semantics

WRITE마다 Runtime이 Idempotency Key를 생성한다.

Idempotency Key는 Runtime execution 자체가 아니라 **동일한 업무 WRITE를 식별하는 Stable BusinessOperationId**에 연결한다.

권장 Logical Model:

```text
BusinessOperationId        # suspend/resume/re-execution/reconciliation 동안 유지
+
write_node_id
        ↓
IdempotencyKey

Canonical Write Arguments
        ↓
PayloadHash
```

`IdempotencyKey`와 `PayloadHash`는 서로 다른 의미를 가진다.

```text
동일 Key + 동일 PayloadHash
→ Original Business Result 반환

동일 Key + 다른 PayloadHash
→ IDEMPOTENCY_CONFLICT
```

Idempotency의 최종 durable 보장은 Tool Contract와 Canonical Business API가 담당한다.

---

# 7. Commit State

WRITE Result에는 최소 다음 상태가 필요하다.

```text
COMMITTED
NOT_COMMITTED
UNKNOWN_COMMIT_STATE
```

`UNKNOWN_COMMIT_STATE` 예:

```text
ERP Commit 성공
→ 응답 전 Network Timeout
→ Runtime은 Commit 여부를 확정할 수 없음
```

이 상태에서 자동 재시도는 금지한다.

권장 Runtime 상태:

```text
RECONCILIATION_REQUIRED
```

---

# 8. Post-Write Verification

WRITE 성공 응답만으로 최종 성공을 선언하지 않는 것을 권장한다.

```text
WRITE
 ↓
Commit Result
 ↓
Post-Write Verification
 ↓
Verified Business Reference
 ↓
EMIT
```

Tool Contract가 Verification 방법 또는 Reference를 제공해야 한다.

---

# 9. Integrity / Authenticity / Trust Boundary

v0.1:

```text
NSO Semantic / Artifact Integrity
+
NSP Package Signature Verification
```

v0.2는 별도의 중복 `.nso` Signature 경로를 기본으로 만들지 않고, 기존 **Signed NSP → Verified Package Trust Boundary**를 재사용한다.

```text
Signed NSP Package
    ↓
Package Signature / Trusted Key Verification
    ↓
Verified Package / Verified Skill Artifact
    ↓
Runtime Preflight
```

WRITE 실행 시 Runtime Preflight는 최소 다음을 확인한다.

```text
Verified Package Trust Evidence
Skill Version / IR Feature Support
WRITE Capability Allowed
Tool Contract Hash Match
```

Tenant/User별 Risk 허용 여부, MFA, 조직별 정책 등은 Canonical Tool Contract에 하드코딩하지 않고 외부 Policy/OA Decision으로 처리하며, NSL Runtime은 해당 Decision Evidence를 검증한다.

---

# 9.1 Control / Execution Responsibility Baseline

Controlled Write의 책임 경계는 다음과 같이 고정한다.

| 영역 | Agent / Platform | NSL | Canonical Business API |
|---|---|---|---|
| Intent / Parameter 결정 | O | 검증만 | - |
| BusinessOperationId | 생성/전달 | 소비/보존 | Idempotency domain에서 사용 |
| Approval Routing / UI | O | Request/Evidence semantics | - |
| Resume Scheduling | O | Resume Request 처리 | - |
| Retry / Reconciliation 결정 | O | Evidence/상태 반환 | 조회/확인 API 제공 |
| Risk / Entitlement 정책 결정 | O | Decision Evidence 검증 | - |
| Atomic Transaction | - | 요구/검증 | O |
| Durable Idempotency | - | Key/PayloadHash 전달 | O |
| Write-time Business Preconditions | - | Contract/Evidence 확인 | O |

NSL은 계속 **Deterministic Skill Execution Plane**으로 유지하며, Control Plane의 업무 orchestration을 흡수하지 않는다.

---

# 10. Version Baseline

| 항목 | v0.1 | v0.2 Baseline |
|---|---|---|
| NSL Language | 0.1 | 0.2 |
| NSO IR | 1.0 | 1.1 |
| SRS 문서 | v1.1 | v2.0 Draft |
| Compiler Design | v0.1 | v0.2 |
| Compiler Python Interface | v0.1 | v0.2 |
| Shared Core/IR | v0.1 | v0.2 |
| NSO Schema 문서 | v0.2 | v0.3 |
| Runtime Validation | v0.1 | v0.2 |
| ExecutionContext | v0.1 | v0.2 |
| Runtime Class Model | v0.1 | v0.2 |
| Runtime Python Interface | v0.1 | v0.2 |
| Tool Contract | v0.1 | v0.2 |

---

# 11. NSL v0.2 Implementation Baseline Documents

## Level 0 — Frozen Architecture Decisions

1. **NSL v0.2 Architecture Delta Decision Record v1.0 — FROZEN**
2. **NSL v0.2 Batch A — Execution Contract Alignment Decision Record v1.0 — FROZEN**
3. **NSL v0.2 Batch B — Compiler Architecture Alignment Decision Record v1.0 — FROZEN**
4. **NSL v0.2 Batch C — Runtime Architecture Alignment Decision Record v1.0 — FROZEN**
5. **NSL v0.2 Architecture Consistency Closure and Unified Change Ledger v1.0 — FROZEN**

이 Level 0 문서들은 기존 03~12 상세문서를 대체하는 것이 아니라, 상세문서가 반드시 따라야 할 **Architecture Decision / Alignment Baseline**을 제공한다.

## Level 1 — Requirements

1. **NSL v0.2 Interpreter & Runtime SRS v2.0 Draft**

## Level 2 — Cross-Cutting Architecture

2. **NSL v0.2 Controlled Write / Approval / Idempotency Detailed Design v0.1**
3. **NSL Shared Core / IR Single Source of Truth Detailed Design v0.2**

## Level 3 — Execution Contract

4. **NSL Object (.nso) IR Schema Detailed Design v0.3**
   - actual `ir_version = 1.1`

5. **NSL Tool Contract Detailed Design v0.2**

## Level 4 — Compiler

6. **NSL Compiler Detailed Design v0.2**
7. **NSL Compiler Python Class / Interface Detailed Design v0.2**

## Level 5 — Runtime Semantics / State

8. **NSL Runtime Validation Semantics Detailed Design v0.2**
9. **NSL Runtime ExecutionContext Detailed Design v0.2**

## Level 6 — Runtime Implementation

10. **NSL Runtime Class/Object Model Detailed Design v0.2**
11. **NSL Runtime Python Interface / Protocol Detailed Design v0.2**

---

# 12. 문서 갱신 순서 — Fixed

다음 순서를 고정한다.

```text
01 Scope / Baseline 확정
       ↓
02 Controlled Write / Approval / Idempotency
       ↓
03 SRS v2.0
       ↓
04 Shared Core / IR v0.2
       ↓
05 NSO IR 1.1 / Schema Doc v0.3
       ↓
06 Tool Contract v0.2
       ↓
07 Compiler Design v0.2
       ↓
08 Compiler Python Interface v0.2
       ↓
09 Validation Semantics v0.2
       ↓
10 ExecutionContext v0.2
       ↓
11 Runtime Class Model v0.2
       ↓
12 Runtime Python Interface v0.2
       ↓
13 Architecture Consistency Closure / Change Ledger
       ↓
14 Source Markdown Alignment (00~12)
       ↓
15 Codex Upgrade Implementation
       ↓
16 Regression / New Feature Test
```

이 순서는 변경하지 않는 것을 원칙으로 한다.

---

# 13. Backward Compatibility

v0.2 구현은 다음 Compatibility를 목표로 한다.

```text
v0.1 .ns
→ v0.2 Compiler에서 Compile 가능

v0.1 .nso / IR 1.0
→ v0.2 Runtime에서 실행 가능

v0.2 .nso / IR 1.1
→ WRITE / APPROVE 지원

Language NSL 0.1
→ IR 1.0

Language NSL 0.2
→ IR 1.1
```

Language Version은 Source 선언이 authoritative하며, Compiler option으로 임의 override하지 않는다.

기존 v0.1 Test Suite는 v0.2의 필수 Regression Suite가 된다.

---

# 14. 대표 Acceptance Vertical Slice

## UC-W01 전표 Draft 생성

```text
Natural Language
→ Account Candidate
→ Project Validation
→ Amount/Period Validation
→ Approval
→ FINANCE.CREATE_VOUCHER_DRAFT
→ Verify
→ Voucher Reference
```

## UC-W02 프로젝트 Draft 생성

```text
Natural Language
→ Name / Duplicate Check
→ Parent Project Check
→ Period / Team / Authority Check
→ Approval
→ PROJECT.CREATE_PROJECT_DRAFT
→ Verify
→ Project Reference
```

초기 Acceptance에서는 CREATE_DRAFT 중심으로 검증하고, 실제 Final/Post 기능은 후속 단계로 둔다.

---

# 15. 구현 Branch / Release 권장

```text
v0.1 stable tag 유지

feature/nsl-v0.2-controlled-write
```

기존 v0.1 구현을 직접 파괴적으로 변경하지 않는다.

---

# 15.1 Closure Alignment Trace

본 문서에 적용한 주요 Unified Change Ledger 항목:

```text
CHG-001  Document authority hierarchy 통일
CHG-003  BusinessOperationId baseline 반영
CHG-004  IdempotencyKey / PayloadHash 분리
CHG-006  Approval workflow ownership → Agent/Platform
CHG-010  Signed NSP trust boundary 재사용
CHG-011  Approval↔WRITE exactly 1:1
CHG-014  Language version → IR version deterministic mapping
CHG-017  Write-time business precondition 책임 경계 명시
CHG-023  Risk classification / PolicyDecision 분리
```

본 문서의 역할은 위 세부 계약을 모두 구현 수준으로 정의하는 것이 아니라, 이후 SRS/IR/Tool/Compiler/Runtime 문서가 따라야 할 Scope·Authority·Version·Responsibility Baseline을 고정하는 것이다.

---

# 16. 최종 정의

> **NSL v0.2는 v0.1의 안전한 조회·계산·검증 기반 위에 명시적 승인, 중복 방지, Commit 불확실성 처리, 서명 검증을 추가하여 기업 시스템에 제한된 Side Effect를 안전하게 생성하는 Controlled Write Language이다.**

본 문서를 NSL v0.2 문서/구현 업그레이드의 **Scope / Version / Document Authority Baseline**으로 사용한다.  
Cross-cutting semantic architecture는 Frozen Architecture Decision 문서와 Controlled Write Architecture를, normative behavior는 SRS를 따른다.
