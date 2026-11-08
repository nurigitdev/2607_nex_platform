# NSL v0.1 → v0.2 Upgrade

## Implementation Instructions / MASTER_PROMPT

**Target:** NSL 0.2 / NSO IR 1.1  
**Python Baseline:** 3.12+  
**Theme:** Controlled Write  
**Purpose:** Codex가 NSL v0.1 코드를 v0.2로 안전하게 업그레이드하기 위한 최상위 실행 지침  
**Architecture Closure Alignment:** `NSL v0.2 Architecture Consistency Closure and Unified Change Ledger v1.0 — FROZEN`

> 이 문서는 **Implementation Process / Guardrail**의 최상위 기준이다. Scope/Version은 Document Baseline, Cross-Cutting Semantics는 Frozen Architecture Decision/Controlled Write Architecture, Normative Requirement는 SRS, Component 구현은 Detailed Design을 따른다. 읽기 순서와 문서 권한(Authority)은 동일한 개념이 아니다.

---

## 1. 시작 원칙

기존 v0.1 코드를 바로 수정하지 말 것. 먼저 Repository 전체를 읽고 다음을 작성한다.

**Repository 실제 구조가 문서의 예시 Package Tree보다 우선한다.** 문서의 `core/`, `ir/`, `runtime/` 등은 우선 Logical Responsibility Boundary로 해석하며, 문서 구조에 맞추기 위한 물리 Package 재배치는 하지 않는다.

```text
docs/upgrade/v0.2/current_architecture.md
docs/upgrade/v0.2/impact_map.md
```

반드시 확인:

```text
package tree / core / ir / lexer / parser / AST
compiler pass / tool contract / runtime engine
execution context / validation / replay / CLI
tests / coverage / compiler↔runtime dependency
```

**Phase 0에서는 Behavior 변경 금지.**

---

## 2. 문서 읽는 순서와 Authority

구현 시작 전 다음 Frozen Decision 문서를 먼저 읽는다.

```text
NSL v0.2 Architecture Consistency Closure and Unified Change Ledger v1.0 — FROZEN
NSL v0.2 Architecture Delta Decision Record v1.0 — FROZEN
NSL v0.2 Batch A — Execution Contract Alignment Decision Record v1.0 — FROZEN
NSL v0.2 Batch B — Compiler Architecture Alignment Decision Record v1.0 — FROZEN
NSL v0.2 Batch C — Runtime Architecture Alignment Decision Record v1.0 — FROZEN
```

그 다음 원본/정렬된 설계 문서는 다음 순서로 읽는다.

1. `NSL v0.1 → v0.2 Upgrade Implementation PRD v1.0`
2. `NSL v0.2 Document Baseline & Upgrade Plan v1.0`
3. `NSL v0.2 Controlled Write / Approval / Idempotency Detailed Design v0.1`
4. `NSL v0.2 Interpreter & Runtime SRS v2.0 Draft`
5. `NSL Shared Core / IR Single Source of Truth Detailed Design v0.2`
6. `NSL Object (.nso) IR Schema Detailed Design v0.3 — IR 1.1`
7. `NSL Tool Contract Detailed Design v0.2`
8. `NSL Compiler Detailed Design v0.2`
9. `NSL Compiler Python Class / Interface Detailed Design v0.2`
10. `NSL Runtime Validation Semantics Detailed Design v0.2`
11. `NSL Runtime ExecutionContext Detailed Design v0.2`
12. `NSL Runtime Class/Object Model Detailed Design v0.2`
13. `NSL Runtime Python Interface / Protocol Detailed Design v0.2`

### 2.1 문서 Authority Rule

문서 간 충돌은 단순한 목록 순서가 아니라 **Concern별 Authority**로 해결한다.

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

Upgrade PRD
  → Implementation Plan / Phase / Milestone
```

**Frozen Architecture Closure/ADR와 상충하는 의미론·책임 경계 변경은 임의로 허용하지 않는다.** 필요한 경우 먼저 ADR을 명시적으로 개정한다.

---

## 3. 절대 변경하면 안 되는 Safety Invariants

```text
S-01 CHECK FAIL     → WRITE 금지
S-02 CHECK UNKNOWN  → WRITE 금지

S-03 Approval 없음/Pending/Rejected/Expired → WRITE 금지
S-04 Approval Evidence write_intent_hash != 재계산 write_intent_hash OR Approval Evidence PayloadHash != 현재 Canonical PayloadHash → WRITE 금지

S-05 Production WRITE Skill이 Trusted Verified Signed NSP Package에서 검증되지 않음 → WRITE 금지
S-06 Tool Contract Hash mismatch → WRITE 금지

S-07 capability != WRITE → Compile/Preflight Reject
S-08 atomicity != ATOMIC → WRITE 금지
S-09 idempotency 미지원 → WRITE 금지

S-10 동일 Idempotency Key + 다른 Payload → IDEMPOTENCY_CONFLICT

S-11 UNKNOWN_COMMIT_STATE
     → 자동 Retry 금지
     → RECONCILIATION_REQUIRED

S-12 Replay/Test → Live WRITE 절대 호출 금지

S-13 WRITE inside FOREACH → Compile Error
S-14 Skill당 WRITE Node > 1 → Compile Error

S-15 Approval은 FAIL/UNKNOWN을 Override할 수 없음
S-16 v0.1 READ-only Skill Behavior는 변경하지 않음
```

---

## 4. v0.2 Scope

지원:

```text
READ / LET / FOREACH / CHECK / EMIT
INCLUDE / true / false
APPROVE / WRITE

WRITE operation:
CREATE / CREATE_DRAFT
```

이번 버전에서 구현하지 않음:

```text
UPDATE / DELETE / CANCEL / POST / FINALIZE
try/catch / rollback keyword / retry keyword
multiple WRITE / FOREACH bulk WRITE
Runtime 내부 LLM 호출
Dynamic WRITE Tool Selection
```

복합 Transaction은 **Canonical Business API**가 책임진다.

---

## 5. Architecture Rule

```text
core/ = Stable Semantic Kernel
ir/   = Stable Execution Contract
```

Compiler와 Runtime이 Type/IR을 중복 정의하지 말 것.

```text
compiler !→ runtime
runtime  !→ compiler
tools    !→ runtime
validation !→ runtime

ir       → core
compiler → core + ir + tool contract
runtime  → core + ir + tool/runtime protocol
```

`WriteExpression`, `ApprovalStatement`, `CommitState`, `ApprovalStatus`는 Single Source of Truth로 유지한다.

위 `core/`, `ir/` 표기는 **Logical Ownership**을 의미한다. 실제 v0.1 Repository의 물리 Module/Layout은 Phase 0에서 확인한 구조를 기준으로 하며, 문서 예시를 맞추기 위한 Big-bang Package Reorganization은 금지한다.

---

## 6. 구현 Phase — 순서 고정

```text
P0  Repository Reconnaissance / Impact Map
P1  v0.1 Baseline Lock + Architecture Test
P2  Shared Core v0.2
P3  IR 1.1
P4  Tool Contract v0.2

P5  Compiler Syntax / AST
P6  Compiler Semantic / WriteSafetyAnalyzer
P7  Compiler Lowering / IR 1.1

P8  Validation / PreWriteEligibility
P9  ExecutionContext v0.2
P10 Approval Suspend / Resume
P11 Write Port / Idempotency / Commit State
P12 WriteGuard / RuntimePreflight
P13 Signed NSP Package Trust / Authenticity
P14 Post-Write Verification
P15 Replay / Mock Safety

P16 Voucher Draft Vertical Slice
P17 Project Draft Vertical Slice
P18 CLI / Developer UX
P19 Full Regression / Quality Gate
```

**한 Phase의 Test가 통과하기 전 다음 Phase로 넘어가지 말 것.**

---

## 7. Refactoring Rule

기능 추가 전에 구조가 v0.2 확장을 감당하기 어렵다면:

```text
구조 검토
→ Refactoring
→ 기존 Regression PASS
→ Feature 추가
```

가능하면 Refactoring Commit과 Feature Commit을 분리한다.

Physical Package/Module 변경은 다음 조건을 모두 만족할 때만 수행한다.

```text
실제 Repository complexity/coupling 문제 확인
→ Behavior-preserving Refactoring
→ 전체 v0.1 Regression PASS
→ Architecture Test PASS
→ 그 다음 v0.2 Feature 추가
```

문서의 권장 Package Tree를 맞추기 위한 Refactoring은 하지 않는다.

**Big-bang Rewrite 금지.**

---

## 8. Test Rule

각 Phase마다 최소:

```text
Unit Test
Negative Test
Regression Test
Architecture Test
Coverage
```

신규 기능은 다음 관점으로 테스트한다.

```text
Boundary Value
Robustness
Worst Case
State Transition
Failure / Recovery
```

반드시 테스트:

```text
write without approval
write using READ tool
write in foreach
two writes
FAIL before write
UNKNOWN before write
approval reject / expire / tamper
intent hash mismatch
idempotent duplicate
idempotency conflict
COMMITTED / NOT_COMMITTED / UNKNOWN_COMMIT_STATE
verification failure
signature tamper
replay no-live-write
IR 1.0 backward compatibility
```

Coverage / Runtime Baseline:

```text
Python    >= 3.12
Statement >= 95%
Branch    >= 90%
```

v0.1 Verified Baseline보다 Quality Gate를 낮추지 않는다.

---

## 9. Commit Rule

Commit 전 반드시:

```text
1. 해당 Phase Unit Test PASS
2. 전체 v0.1 Regression PASS
3. 신규 v0.2 Regression PASS
4. Architecture Test PASS
5. Coverage Gate PASS
6. 기존 Test 삭제/무력화 없음
```

권장 Milestone:

```text
M0 baseline
M1 core
M2 IR 1.1
M3 tool contract
M4 parser/AST
M5 compiler write safety
M6 validation
M7 execution context
M8 approval/resume
M9 write/idempotency/commit
M10 package trust/preflight
M11 verification/replay
M12 voucher vertical slice
M13 project vertical slice
M14 full regression
```

---

## 10. 대표 Vertical Slice

### Voucher Draft

```text
READ account/project/period
→ CHECK all PASS
→ APPROVE
→ suspend
→ resume
→ WriteGuard
→ Idempotency
→ FINANCE.CREATE_VOUCHER_DRAFT
→ CommitState
→ FINANCE.GET_VOUCHER verify
→ EMIT
```

### Project Draft

```text
READ duplicate/parent/authority
→ CHECK
→ APPROVE
→ PROJECT.CREATE_PROJECT_DRAFT
→ VERIFY
→ EMIT
```

---

## 11. 완료 정의

v0.2 완료는 `write` Keyword가 실행되는 것으로 판단하지 않는다.

다음이 모두 만족되어야 한다.

```text
v0.1 compatibility 유지
IR 1.0 + IR 1.1 지원
Compiler Write Safety 동작
FAIL/UNKNOWN WRITE 차단
Approval Suspend/Resume 동작
Intent Hash 검증
Idempotency 동작
UNKNOWN Commit 자동 Retry 없음
Production Signed NSP Package Trust 검증
Replay Live WRITE 없음
Voucher/Project Vertical Slice PASS
Statement >=95%, Branch >=90%
Architecture Test PASS
```

---

## 12. 최종 구현 원칙

> **NSL v0.2의 목표는 WRITE 기능 추가가 아니라 Controlled Write 구현이다.**

```text
Validate
→ Approve
→ Freeze Intent
→ Suspend / Resume
→ Verify Approval
→ WriteGuard
→ Idempotent Atomic WRITE
→ Commit State
→ Verify
```

**이 흐름을 우회하는 Shortcut을 만들지 말 것.**


---

## 13. Closure Alignment Trace

본 MASTER_PROMPT 개정에는 Unified Change Ledger의 다음 항목을 반영한다.

```text
CHG-001  Document Authority Hierarchy 통일
CHG-002  Quality Gate 95/90 + Python 3.12+
CHG-032  Physical Package Refactor는 Repository-first
```

또한 동일한 Frozen Trust Model을 명확히 하기 위해 Production WRITE의 Signature 표현을 **Trusted Verified Signed NSP Package** 기준으로 정규화하였다.

이 문서의 역할은 Process / Safety / Quality Guardrail이며, 이후 원본 문서 수정에서 새로운 Semantic Architecture를 추가하지 않는다.
