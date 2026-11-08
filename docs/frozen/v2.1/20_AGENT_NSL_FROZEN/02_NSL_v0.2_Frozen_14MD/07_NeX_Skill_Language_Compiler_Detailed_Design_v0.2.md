# NeX Skill Language Compiler Detailed Design v0.2

**문서 버전:** v0.2 — Closure Aligned  
**작성일:** 2026-08-23  
**대상:** NSL Language v0.1 / v0.2 Compiler  
**Target IR:** NSO IR 1.0 / 1.1  
**기본 Profile:** `NSL-0.2-STRICT`  
**Architecture Closure 기준:** `NSL v0.2 Architecture Consistency Closure and Unified Change Ledger v1.0 — FROZEN`

---

# 1. 목적

v0.1 Compiler Pipeline과 deterministic lowering/hash semantics를 유지하면서 Controlled Write에 필요한 Syntax, Semantic Resolution, Tool Contract Resolution, Approval Link, Write Safety Analysis, IR 1.1 Lowering을 추가한다.

```text
.ns
 ↓
Language Version Resolution
 ↓
Lexer / Parser
 ↓
Include Composition
 ↓
Declaration / Name
 ↓
Tool Contract Resolution
 ↓
Type Check
 ↓
Approval / Write Semantic Check
 ↓
Safety / Resource / Write Analysis
 ↓
Lowering
 ↓
Canonical IR
 ├─ NSL 0.1 → IR 1.0
 └─ NSL 0.2 → IR 1.1
 ↓
Canonical Serialization / Semantic Hash
```

중요한 Closure 원칙:

```text
Compiler = Static Proof / Canonical Artifact Builder

Compiler !→ BusinessOperationId generation
Compiler !→ ApprovalRequestId generation
Compiler !→ IdempotencyKey generation
Compiler !→ Runtime PayloadHash generation
Compiler !→ Tenant/User policy decision
Compiler !→ Approval workflow orchestration
Compiler !→ Runtime retry/reconciliation decision
```

Production Signing은 Compiler Core의 책임이 아니라 기존 Signed NSP Package Build/Signing Boundary의 책임이다.

---

# 2. v0.2 신규 Keyword

v0.2 Keyword:

```text
write
approve
approved_by
```

v0.1 Keyword는 그대로 유지한다.

단, Keyword 인식은 **Source Language Version에 따라 달라져야 한다.**

```text
language 0.1
→ v0.1 keyword set 사용
→ write / approve / approved_by를 v0.2 keyword로 강제 해석하지 않음

language 0.2
→ v0.1 keyword set + write / approve / approved_by
```

이 규칙은 v0.1 source compatibility를 보호한다.

Source Language declaration이 authoritative하며, Compiler Option으로 Source Language Version을 임의 override해서는 안 된다.

---

# 3. Source Syntax

```nsl
approve VOUCHER_CREATE {
    message "전표 Draft를 등록하시겠습니까?";
}

let voucher =
    write FINANCE.CREATE_VOUCHER_DRAFT(
        account_code = account_code,
        project_code = project_code,
        amount = amount
    )
    approved_by VOUCHER_CREATE;
```

---

# 4. Grammar

```ebnf
approve_stmt
  = "approve" identifier
    "{"
      "message" string_literal ";"
    "}"
  ;

write_expr
  = "write" qualified_name
    "(" argument_list? ")"
    "approved_by" identifier
  ;
```

v0.2에서는 `approved_by` 생략을 허용하지 않는다.

---

# 5. AST 추가

```text
ApproveStatementAst
WriteExpressionAst
```

개념:

```python
@dataclass(frozen=True)
class ApproveStatementAst:
    node_id: AstNodeId
    approval_id: str
    message: str
    span: SourceSpan
```

```python
@dataclass(frozen=True)
class WriteExpressionAst:
    node_id: AstNodeId
    tool_name: QualifiedName
    arguments: tuple[ArgumentAst, ...]
    approval_id: str
    span: SourceSpan
```

---

# 6. Approval Namespace

기존 Namespace:

```text
Value
Check
Tool
Builtin
Type
```

v0.2 추가:

```text
Approval
```

같은 Approval ID 중복은 Compile Error다.

`ApprovalId`는 Source/IR의 정적 식별자다.

```text
ApprovalId
≠ Runtime ApprovalRequestId
```

Compiler는 Runtime의 ApprovalRequestId를 생성하지 않는다.

---

# 7. Declaration Collection

Approval 선언을 DeclarationIndex에 추가한다.

```text
approval_declarations
```

Approval ID는 Skill Scope에 존재하며 v0.2에서는 Loop 내부 선언을 금지한다.

`NSL-0.2-STRICT`에서는 이후 Write Safety Analysis가 다음을 추가 검증할 수 있도록 DeclarationIndex / SemanticModel에 충분한 static relation을 보존해야 한다.

```text
approval declaration count
approval → linked write
write → approval
unused approval
approval sharing
```

실제 Runtime Approval Request instance나 Approval Evidence는 Compiler symbol table에 넣지 않는다.

---

# 8. Name Resolution

`approved_by VOUCHER_CREATE`는 Approval Symbol로 Resolve한다.

기본 검증:

```text
approval exists
unique
declared before write
same skill
```

추가적으로 `NSL-0.2-STRICT`의 Write Safety Pass가 다음을 증명해야 한다.

```text
each WRITE has exactly one Approval
each Approval maps to exactly one WRITE
unused Approval == 0
one Approval shared by multiple WRITE == compile error
```

Name Resolution은 symbol/reference 연결을 담당하고, exact 1:1 관계의 최종 Safety 판정은 Write Safety Analyzer가 담당한다.

---

# 9. Tool Contract Resolution

READ Tool과 WRITE Tool을 구분한다.

`write`는 다음 **Tool Contract structural semantics**를 만족해야 한다.

```text
tool declared in requires
contract exists
capability == WRITE
operation_kind in {CREATE, CREATE_DRAFT}
risk_level exists
idempotency.required == true
atomicity == ATOMIC
approval.required == true
```

Safety-critical Tool Contract field는 raw string 비교보다 shared typed model을 사용해야 한다.

```text
ToolCapability
OperationKind
Atomicity
RiskLevel
```

Compiler는 다음을 결정하지 않는다.

```text
이 Tenant가 R4를 허용하는가?
현재 Principal에게 WRITE entitlement가 있는가?
MFA가 필요한가?
현재 Policy가 ALLOW인가?
```

이는 Runtime의 external PolicyDecision / Policy Evidence 책임이다.

v0.1 Tool Contract schema를 파괴적으로 변경하지 않고 WRITE metadata를 additive하게 해석해야 한다.

---

# 10. Type Checking

WRITE Argument Type은 Tool Contract Input과 일치해야 한다.

WRITE Expression Result Type은 Tool Contract Output Type이다.

예:

```text
FINANCE.CREATE_VOUCHER_DRAFT
→ VoucherDraft
```

따라서:

```nsl
let voucher = write ...
```

에서 `voucher: VoucherDraft`로 추론한다.

---

# 11. Write Safety Analyzer

v0.2 Compiler의 핵심 신규 Pass다.

`NSL-0.2-STRICT`에서 다음을 정적으로 증명한다.

```text
WSA-001 WRITE count <= 1
WSA-002 WRITE not inside foreach
WSA-003 WRITE has approval
WSA-004 approval declared before write
WSA-005 Approval↔WRITE exactly 1:1
WSA-006 unused Approval == 0
WSA-007 tool capability == WRITE
WSA-008 operation_kind supported
WSA-009 atomicity == ATOMIC
WSA-010 idempotency.required == true
WSA-011 risk metadata exists / structurally valid
WSA-012 no dynamic write tool
WSA-013 no unsupported transaction semantics
WSA-014 required operation metadata complete
```

이 Pass는 Runtime policy를 결정하지 않는다.

```text
Compile-time:
  static structure / contract safety proof

Runtime:
  actual CHECK result
  Approval Evidence
  current PolicyDecision
  Business Preconditions
  Idempotency / Commit outcome
```

`WriteSafetyAnalysis`는 위 proof 결과를 passive metadata로 남길 수 있다.

---

# 12. Approval Dominance

현재 v0.2에는 if/else가 없으므로 Control Flow가 단순하다.

Approval Statement는 해당 WRITE보다 선행해야 한다.

```text
APPROVE
   ↓
other pure/read/check statements allowed
   ↓
WRITE
```

하지만 Approval 이후 Write Argument가 변경될 수 있는 Mutable Assignment는 원래 NSL Immutable Binding 때문에 불가능하다.

Runtime은 별도로 Write Intent Hash를 확인한다.

---

# 13. WRITE inside FOREACH 금지

예:

```nsl
foreach item in items max 100 {
    write PROJECT.CREATE_PROJECT_DRAFT(...)
}
```

Compile Error:

```text
NSL-E5201
WRITE is not allowed inside FOREACH in NSL-0.2-STRICT
```

이 제한은 Bulk Partial Commit 문제를 피하기 위한 것이다.

중요:

```text
allow_write_in_foreach = false
```

같은 safety-critical rule을 일반 Compiler Option으로 제공하여 production compile에서 임의 완화해서는 안 된다.

해당 규칙은 `NSL-0.2-STRICT` SemanticsProfile의 immutable safety invariant다.

---

# 14. Multiple WRITE 금지

```nsl
let a = write ...
let b = write ...
```

Compile Error:

```text
NSL-E5202
Only one WRITE node is allowed per skill in NSL-0.2-STRICT
```

복합 Transaction은 Canonical Business API 하나로 캡슐화한다.

중요:

```text
max_write_nodes = 1
max_write_calls = 1
```

은 일반 CompilerOptions로 임의 변경할 수 있는 tuning knob가 아니라 `NSL-0.2-STRICT` SemanticsProfile의 safety invariant다.

---

# 15. CHECK와 WRITE 관계

Compiler가 실제 Runtime CHECK 결과는 알 수 없지만, Write Safety Metadata를 생성한다.

IR analysis:

```text
requires_all_checks_resolved = true
block_on_fail = true
block_on_unknown = true
```

Runtime WriteGuard가 실행 시 강제한다.

---

# 16. Risk Static Validation

Compiler는 Tool/Skill의 `RiskLevel` metadata를 읽고 다음만 검증한다.

```text
risk metadata exists
risk enum/value valid
tool contract와 required-tool fingerprint가 일치
static skill metadata가 complete
```

Compiler는 Tenant/User별 Risk entitlement를 결정하지 않는다.

```text
RiskLevel
= static classification metadata

PolicyDecision
= tenant/user/environment별 현재 allow/deny
```

따라서 다음은 Runtime Preflight / WriteGuard + external Policy/OA 책임이다.

```text
principal entitlement
tenant risk allowance
MFA requirement
time-varying policy
deployment/environment policy
```

Compiler가 현재 policy allow/deny를 Compile Error로 고정해서는 안 된다.

---

# 17. Signed IR와 Compiler 역할

Compiler Core는 Canonical IR과 Source/Semantic Hash를 생성한다.

```text
Compiler Core
  ├─ Canonical IR
  ├─ SourceBundleHash
  └─ SemanticHash
```

Production Signing은 Compiler Core 밖에서 기존 Signed NSP Package pipeline이 담당한다.

```text
Canonical NSO / Skill Artifact
        ↓
NSP Build
        ↓
Package Integrity / Publisher Signature
        ↓
Verified Signed NSP
```

따라서 Compiler Core에 별도의 `NsoArtifactSigner` 또는 Private Signing Key를 추가하지 않는다.

Compiler는 WRITE-bearing Skill에 다음과 같은 **trust requirement metadata**를 남길 수 있다.

```text
requires_verified_package_for_write = true
```

이 flag의 의미는 다음과 같다.

```text
Production WRITE execution
→ Verified Signed NSP trust evidence required
```

Compiler가 package signature를 직접 생성하거나 검증한다는 뜻이 아니다.

---

# 18. Resource Bound

기존 Tool Call Bound에 WRITE를 포함한다.

```text
ToolCalls(WRITE) = 1
```

`NSL-0.2-STRICT`:

```text
max_write_calls = 1
```

Approval 자체는 Tool Call이 아니라 Runtime Control/Suspend Event다.

`max_write_calls = 1`은 generic Compiler Option으로 완화하지 않고 SemanticsProfile의 immutable Safety Rule로 취급한다.

---

# 19. Lowering

Source:

```nsl
approve A { message "..."; }

let result =
    write FINANCE.CREATE_VOUCHER_DRAFT(...)
    approved_by A;
```

IR:

```text
ApprovalStatement(
  approval_id=A
)

LetStatement(
  value=WriteExpression(
    tool_ref=tool0003,
    approval_ref=A
  )
)
```

---

# 20. Static Analysis IR

Compiler가 생성 가능한 passive analysis metadata 예:

```json
{
  "write_analysis": {
    "write_node_count": 1,
    "approval_node_count": 1,
    "approval_write_mapping_count": 1,
    "unused_approval_count": 0,
    "max_write_calls": 1,
    "writes_inside_loop": false,
    "all_writes_approved": true,
    "all_approval_write_links_exact": true,
    "supported_operation_metadata_complete": true,
    "risk_metadata_complete": true,
    "requires_verified_package_for_write": true
  }
}
```

Static Analysis에는 다음 runtime values를 넣지 않는다.

```text
BusinessOperationId
ApprovalRequestId
IdempotencyKey
PayloadHash
PolicyDecision
CommitState of an execution
Verification result
```

Compiler는 runtime invocation identity를 생성하지 않는다.

---

# 21. Diagnostic Namespace

신규 범위:

```text
NSL-E52xx Write Safety
NSL-E53xx Approval
NSL-E54xx Write Tool Contract
```

예:

```text
NSL-E5201 write in foreach
NSL-E5202 multiple writes
NSL-E5301 unknown approval
NSL-E5302 approval after write
NSL-E5401 write using non-WRITE tool
NSL-E5402 non-atomic tool
NSL-E5403 idempotency unsupported
```

---

# 22. Compiler Pipeline v0.2

```text
P01 Source Bundle
P02 Language Version Resolution
P03 Lexer
P04 Parser
P05 Include
P06 Declaration
P07 Name
P08 Tool Contract
P09 Type
P10 Semantic
P11 Safety
P12 Write Safety
P13 Resource Bound
P14 Lowering
      ├─ Language 0.1 → IR 1.0
      └─ Language 0.2 → IR 1.1
P15 IR Structural Validation
P16 Canonical Serialization
P17 SourceBundleHash / SemanticHash
```

이후 Production artifact lifecycle:

```text
Compiler Output
   ↓
NSP Build
   ↓
Package Signing
   ↓
Verified Package Trust
```

Signing은 Compiler Core Pipeline의 내부 Pass가 아니다.

---

# 23. Backward Compatibility

Source Language Version과 Target IR Version mapping을 deterministic하게 고정한다.

```text
NSL Language 0.1
→ IR 1.0

NSL Language 0.2
→ IR 1.1
```

따라서:

```text
v0.1 Source
→ 기존 keyword semantics
→ 기존 deterministic Node ID allocation
→ IR 1.0
→ 기존 canonical serialization / semantic hash 보존

v0.2 Source
→ v0.2 keyword semantics
→ IR 1.1
```

WRITE를 사용하지 않는 v0.2 Source라도 `language 0.2`를 선언했다면 IR 1.1로 compile한다.

Compiler Option으로 Source Language Version 또는 Target IR Version을 임의 override하지 않는다.

Node ID allocator는 새로운 parallel allocator를 만들지 않고 기존 deterministic allocator를 확장해야 한다. v0.1 source의 Node ID / canonical IR / SemanticHash가 v0.2 Compiler 도입 때문에 바뀌어서는 안 된다.

---

# 24. Test

신규 Compiler Tests:

```text
parse approve
parse write
resolve approval
duplicate approval
unknown approval
write before approval

approval↔write exact 1:1
unused approval rejected
one approval shared by multiple writes rejected

write using read tool
unsupported update tool
write inside foreach
two writes
non-atomic write tool
write without idempotency
risk metadata incomplete
unsupported operation metadata

correct write lowering
write analysis flags
compiler does not generate BusinessOperationId
compiler does not generate ApprovalRequestId
compiler does not generate IdempotencyKey
compiler does not generate runtime PayloadHash

language 0.1 keyword compatibility
language 0.1 → IR 1.0
language 0.2 → IR 1.1
write-less language 0.2 → IR 1.1

v0.1 Node ID deterministic regression
v0.1 canonical IR regression
v0.1 SemanticHash regression

WRITE-bearing skill requires verified-package metadata
compiler core contains no signing private key
compiler core does not perform package signing

v0.1 regression
```

Safety-critical profile test:

```text
max_write_nodes cannot be relaxed by generic CompilerOptions
allow_write_in_foreach cannot be enabled by generic CompilerOptions
```

Tool Contract View abstraction을 도입하는 경우에도 `OperationKind`, `Atomicity`, `ToolCapability`, `RiskLevel`과 같은 typed bounded model을 사용해야 한다.

---

# 24.1 Repository-first Refactor Rule

본 문서의 Compiler pass/class/module 명칭은 **logical responsibility model**이다.

실제 구현 시:

```text
1. 현재 v0.1 repository structure를 먼저 확인
2. existing module/class를 가능한 한 확장
3. coupling hotspot이 실제로 존재할 때만 extraction
4. 문서 예시를 맞추기 위한 big-bang package rearrangement 금지
```

예를 들어 `CompilerToolContractView`와 같은 adapter/view abstraction은 실제 Compiler가 Tool Contract implementation detail에 과도하게 결합되어 있을 때만 도입한다.

도입할 경우:

```text
raw str fields
→ 금지/지양

typed OperationKind / Atomicity / ToolCapability / RiskLevel
→ 권장
```

---

# 25. 대표 전표 Compile

```text
voucher_create.ns
 ↓
Compiler
 ↓
Tool Contracts:
ACCOUNT.GET_ACCOUNT
PROJECT.GET_PROJECT
FINANCE.CREATE_VOUCHER_DRAFT
 ↓
Type / Safety
 ↓
Approval/Write Analysis
 ↓
IR 1.1
```

---

# 25.1 Closure Alignment Trace

본 문서에 적용한 주요 Unified Change Ledger 항목:

```text
CHG-010  Signed NSP Trust Boundary 재사용
CHG-011  Approval↔WRITE exactly 1:1
CHG-012  Language-version-aware Keywords
CHG-013  Strict Profile Safety Rules immutable
CHG-014  Language Version → IR Version deterministic mapping
CHG-015  Deterministic Node ID / SemanticHash 보존
CHG-023  Risk Classification / PolicyDecision 분리
CHG-031  Semantic Hash / Package Integrity ownership 분리
CHG-032  Physical Package Refactor = repository-first
```

추가 Boundary Decision:

```text
BusinessOperationId / ApprovalRequestId / IdempotencyKey / PayloadHash
= Runtime invocation identity/evidence
= Compiler 생성 대상 아님
```

본 문서는 Batch B Compiler Freeze의 결정을 실제 Compiler Pass / Static Analysis / Lowering 책임으로 구체화한다.

---

# 26. 최종 정의

> **NSL v0.2 Compiler는 WRITE를 단순히 문법적으로 허용하는 Compiler가 아니라, Runtime이 Controlled Write를 안전하게 실행할 수 있도록 exact Approval↔WRITE Link, Tool Capability/Operation/Atomicity/Idempotency, Risk Metadata, Bounded Side Effect를 정적으로 증명하고 Canonical IR을 deterministic하게 생성하는 Compiler이다. Runtime business identity, current policy, Approval workflow, Commit/Reconciliation은 Compiler 책임이 아니다.**
