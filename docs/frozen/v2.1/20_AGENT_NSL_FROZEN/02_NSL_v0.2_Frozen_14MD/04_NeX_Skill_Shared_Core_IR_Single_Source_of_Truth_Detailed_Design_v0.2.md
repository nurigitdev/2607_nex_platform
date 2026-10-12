# NeX Skill Language Shared Core / IR Single Source of Truth Detailed Design v0.2

**문서 버전:** v0.2 — Closure Aligned  
**작성일:** 2026-08-23  
**대상:** NSL v0.2 Compiler / Runtime / Tool Boundary  
**IR:** NSO 1.1  
**Architecture Closure 기준:** `NSL v0.2 Architecture Consistency Closure and Unified Change Ledger v1.0 — FROZEN`

---

# 1. 목적

v0.1의 Single Source of Truth 원칙을 유지하면서 Controlled Write에 필요한 **최소 공통 의미론 타입과 안정적인 IR Execution Contract**만 추가한다.

```text
core/
  Stable Semantic Kernel
  ├─ shared value/status/identity types
  └─ no external services / no workflow orchestration

ir/
  Stable Static Execution Contract
  ├─ ApprovalStatement / WriteExpression
  └─ no runtime business-operation instance state

compiler/runtime/tools
  depend on core + ir where appropriate
  never duplicate shared semantics
```

중요한 Closure 원칙:

```text
BusinessOperationId
IdempotencyKey
PayloadHash
```

는 여러 Runtime/Tool 경계에서 동일 의미가 필요한 shared type일 수 있으나, **Compiler가 생성하거나 Static IR에 business execution identity로 직렬화하는 대상은 아니다.**

또한 Production WRITE의 Authenticity는 개별 NSO에 별도의 서명 모델을 중복 도입하지 않고 기존 **Signed NSP → Verified Package Trust Boundary**를 재사용한다.

---

# 2. v0.2 변경 원칙

`core/`를 WRITE 구현 객체 저장소 또는 Service Locator로 만들지 않는다.

core 추가 후보는 여러 Layer에서 **동일 의미로 공유되어야 하는 작은 값/식별자/상태 타입**만 허용한다.

```text
BusinessOperationId
IdempotencyKey
PayloadHash

ApprovalStatus
PreWriteEligibility
CommitState
VerificationStatus
RiskLevel
```

다음은 core에 두지 않는다.

```text
ApprovalStore / Approval Workflow
WriteJournal Persistence
CheckpointStore
CommitVerifier
RuntimePolicy Service
Package Signature Verifier
Reconciliation Orchestrator
```

또한 다음 분리를 유지한다.

```text
RiskLevel
= static classification metadata

PolicyDecision
= tenant / user / environment별 현재 허용 판단
```

`PolicyDecision`의 authoring/ownership은 Policy/OA Layer이며 core가 business policy를 하드코딩하지 않는다.

---

# 3. core/ 권장 구조

다음은 **logical responsibility example**이다.

```text
core/
├─ ids.py
├─ types.py
├─ money.py
├─ values.py
├─ data_quality.py
├─ checks.py
├─ capabilities.py
├─ approvals.py       # v0.2 shared approval state types
├─ writes.py          # v0.2 write/commit/verification shared types
├─ risks.py           # v0.2 risk classification
└─ errors.py
```

이 디렉터리/파일 구조는 실제 Repository를 강제로 재배치하라는 의미가 아니다.

```text
Repository-first refactor
→ 현재 구현 구조와 dependency hotspot을 먼저 확인
→ 필요한 최소 위치만 조정
→ 문서 예시를 맞추기 위한 big-bang package rearrangement 금지
```

Single Source of Truth의 핵심은 **물리 파일 개수**가 아니라 동일 의미의 타입이 Compiler/Runtime/Tool에서 중복 정의되지 않는 것이다.

---

# 4. `core/approvals.py`

```python
class ApprovalStatus(str, Enum):
    NOT_REQUESTED = "NOT_REQUESTED"
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"
```

`ApprovalStatus`는 per-execution approval lifecycle을 표현하는 공유 타입이다.

단, 다음을 혼동하지 않는다.

```text
ApprovalStatus
= lifecycle state

ApprovalDecision
= human decision (APPROVED / REJECTED)

ApprovalEvidenceValidation
= approval evidence 검증 결과
```

후자의 구체적인 Runtime DTO/Enum 위치는 Runtime 상세 설계에서 확정할 수 있으며, 동일 타입이 여러 Layer에서 공유될 때만 core로 승격한다.

Approval routing/UI/persistence/notification은 core 또는 IR 책임이 아니다.

---

# 5. `core/writes.py`

```python
class PreWriteEligibility(str, Enum):
    ALLOWED = "ALLOWED"
    BLOCKED = "BLOCKED"
    REQUIRES_APPROVAL = "REQUIRES_APPROVAL"


class CommitState(str, Enum):
    COMMITTED = "COMMITTED"
    NOT_COMMITTED = "NOT_COMMITTED"
    UNKNOWN_COMMIT_STATE = "UNKNOWN_COMMIT_STATE"


class VerificationStatus(str, Enum):
    NOT_REQUESTED = "NOT_REQUESTED"
    VERIFIED = "VERIFIED"
    FAILED = "FAILED"
    UNKNOWN = "UNKNOWN"


IdempotencyKey = NewType("IdempotencyKey", str)
PayloadHash = NewType("PayloadHash", str)
```

Stable business-operation identity는 shared ID type으로 둘 수 있다.

```python
BusinessOperationId = NewType("BusinessOperationId", str)
```

권장 위치는 `core/ids.py`다.

중요한 non-collapse rule:

```text
BusinessOperationId ≠ execution_id ≠ ToolInvocationId
IdempotencyKey ≠ PayloadHash
PreWriteEligibility ≠ CommitState ≠ ExecutionStatus
CommitState ≠ VerificationStatus
```

`RECONCILIATION_REQUIRED`는 PreWriteEligibility 값이 아니다. `UNKNOWN_COMMIT_STATE` 이후 Runtime의 ExecutionStatus/Disposition으로 표현한다.

---

# 6. `core/risks.py`

```python
class RiskLevel(str, Enum):
    R0 = "R0"
    R1 = "R1"
    R2 = "R2"
    R3 = "R3"
    R4 = "R4"
    R5 = "R5"
```

`RiskLevel`은 Tool/Skill의 static classification metadata다.

```text
Compiler
→ metadata 존재/형식/계약 정합성 검증

Runtime
→ 외부 PolicyDecision / Policy Evidence 확인

Policy/OA
→ tenant/user entitlement와 환경별 실제 허용 판단
```

Tenant/User별 allow/deny, MFA, 조직별 추가 승인 조건은 `RiskLevel` 자체에 포함시키거나 core에 하드코딩하지 않는다.

---

# 7. 기존 Type / Value 유지

다음은 v0.1 Single Source of Truth를 그대로 유지한다.

```text
TypeInfo
Money
Presence
Completeness
CheckStatus
CheckSeverity
ValueEnvelope
ToolCapability
```

Runtime은 Type Inference를 수행하지 않는다.

v0.2 도입으로 기존 타입을 이름만 바꾸거나 Compiler/Runtime에 parallel type을 새로 만들지 않는다. 특히 v0.1 deterministic serialization/hash에 관여하는 기존 value model은 additive extension 원칙을 따른다.

---

# 8. ToolCapability

v0.2:

```python
class ToolCapability(str, Enum):
    READ = "READ"
    WRITE = "WRITE"
    TRANSACTION = "TRANSACTION"
```

NSL v0.2 Source의 `write`는 WRITE Capability Tool만 사용한다.

`TRANSACTION`은 향후 확장용이며 v0.2 Source에서 직접 사용하지 않는 것을 권장한다.

Tool Capability는 semantic capability이고, 특정 Principal/Tenant가 현재 해당 WRITE를 실행할 수 있는지는 별도의 external `PolicyDecision`이다.

---

# 9. ir/ 구조

다음 구조는 logical ownership을 나타내는 예시다.

```text
ir/
├─ operators.py
├─ expressions.py
├─ statements.py
├─ policies.py
├─ schema.py
├─ skill.py
├─ analysis.py
├─ integrity.py       # semantic/hash integrity metadata only
├─ debug.py
├─ encoder.py
├─ decoder.py
├─ canonical.py
├─ hashing.py
├─ validator.py
└─ codec.py
```

`ir/`은 Static Execution Contract다.

다음 runtime instance data는 IR에 넣지 않는다.

```text
BusinessOperationId
ApprovalRequestId
IdempotencyKey
PayloadHash of a runtime invocation
PolicyDecision
CommitState of an execution
Verification result
Checkpoint state
```

필요하면 shared type 정의는 core에 존재할 수 있으나, 해당 실행값은 Runtime Request/State/Tool Call에 존재한다.

---

# 10. IR 1.1 추가 Expression

`ir/expressions.py`:

```text
WriteExpression
```

개념:

```python
@dataclass(frozen=True, slots=True)
class WriteExpression:
    node_id: NodeId
    tool_ref: ToolRef
    arguments: tuple[ArgumentBinding, ...]
    approval_ref: str
    type_info: TypeInfo
```

`WriteExpression`은 Static Skill Semantics만 표현한다.

따라서 직접 다음을 보유하지 않는다.

```text
ToolContract object
BusinessOperationId
IdempotencyKey
PayloadHash
ApprovalRequestId
PolicyDecision
Commit outcome
```

이 값들은 Compile-time artifact semantics가 아니라 Runtime invocation/state semantics다.

---

# 11. IR 1.1 추가 Statement

`ir/statements.py`:

```text
ApprovalStatement
```

```python
@dataclass(frozen=True, slots=True)
class ApprovalStatement:
    node_id: NodeId
    approval_id: str
    message: str
    policy: ApprovalPolicy
```

`approval_id`는 Source/IR의 **정적 Approval ID**다.

실제 실행에서 생성되는 `ApprovalRequestId`와 동일한 식별자가 아니며, ApprovalRequestId는 IR에 저장하지 않는다.

---

# 12. ApprovalPolicy

`ir/policies.py`:

```python
@dataclass(frozen=True, slots=True)
class ApprovalPolicy:
    required: bool = True
    ttl_seconds: int | None = None
```

이 Policy는 Skill이 요구하는 **정적 approval semantics**다.

실제 승인자 선택, Role/조직 Rule, Notification, Approval Persistence, Resume Queue Scheduling은 NeX-AE / Agent Platform / Policy Layer에 위임한다.

또한 `ttl_seconds`는 freshness를 완전히 보장하는 write-time business precondition의 대체 수단이 아니다.

---

# 13. RequiredTool v0.2

```python
@dataclass(frozen=True, slots=True)
class RequiredTool:
    tool_ref: ToolRef
    tool_id: ToolId
    version: str
    capability: ToolCapability
    risk_level: RiskLevel
    contract_hash: str
```

`RequiredTool`은 canonical Tool Contract의 **semantic fingerprint/reference**를 보관한다.

Tenant/User entitlement, MFA, network allowlist와 같은 environment-specific policy value는 RequiredTool 또는 canonical contract hash에 섞지 않는다.

WRITE 실행 시 Runtime은 RequiredTool fingerprint와 현재 Tool Contract를 검증하고, 실제 allow/deny는 별도 PolicyDecision으로 확인한다.

---

# 14. StaticAnalysis v0.2

추가 권장 필드:

```text
write_node_count
approval_node_count
approval_write_mapping_count
unused_approval_count
writes_inside_loop
max_write_calls
requires_verified_package_for_write
```

`NSL-0.2-STRICT` 기대값:

```text
write_node_count <= 1
max_write_calls <= 1
writes_inside_loop = false
approval ↔ write mapping = exactly 1:1
unused_approval_count = 0
```

`requires_verified_package_for_write`는 Compiler가 package signature를 직접 생성/검증한다는 뜻이 아니다.

의미:

```text
WRITE-bearing Skill
→ Production execution requires Verified Signed NSP trust evidence
```

Safety-critical WRITE count / FOREACH 제한은 일반 CompilerOptions로 완화할 수 있는 knob가 아니라 Strict SemanticsProfile rule이다.

---

# 15. Integrity Model

IR의 integrity 책임과 Package trust 책임을 분리한다.

```text
Compiler / IR Layer
  SourceBundleHash
  SemanticHash
  Canonical IR serialization

NSP Package Layer
  Package / Artifact Integrity
  Publisher Signature
  Trusted Key / Chain

Runtime Preflight
  Verified Package / Verified Skill Trust Evidence 확인
```

따라서 canonical semantic IR에 별도의 독립 `.nso` signature DTO를 필수로 추가하지 않는다.

`ir/integrity.py`가 존재한다면 의미론적 hash/integrity descriptor를 담당할 수 있으나, 다음은 Package/Security Adapter의 책임이다.

```text
signature bytes
publisher key trust
certificate / key chain
package signature verification
```

Production WRITE는 기존 **Signed NSP → Verified Package** trust boundary를 재사용한다.

---

# 16. IR Validator v0.2

공통 Structural Validation:

```text
write tool_ref exists
write approval_ref exists
approval node unique
approval ↔ write exactly 1:1
unused approval absent
write count <= strict profile limit
write not inside foreach
write required tool capability == WRITE
IR version supported
required tool fingerprint structurally valid
```

다음은 IR Validator 책임이 아니다.

```text
Trusted signing key verification
Tenant/User entitlement
Current PolicyDecision
BusinessOperationId generation
IdempotencyKey generation
Commit/Reconciliation decision
```

Package Trust 검증은 RuntimePreflight가 Verified Package Trust Evidence를 통해 수행한다.

---

# 17. Compiler / Runtime 공유 경계

Compiler:

```text
AST
→ core TypeInfo / RiskLevel / ToolCapability
→ ir ApprovalStatement / WriteExpression
→ StaticAnalysis
→ SkillObject
→ Canonical IR / SemanticHash
```

Runtime:

```text
Verified SkillObject
+ ExecutionRequest
  └─ Principal / DataPolicy / BusinessOperationId
→ Approval / Write Guard
→ Idempotency / Tool Port
→ Commit / Verification
```

동일 IR class와 shared semantic type을 사용한다.

Compiler는 Runtime instance identity를 생성하지 않는다.

```text
Compiler !→ BusinessOperationId
Compiler !→ ApprovalRequestId
Compiler !→ IdempotencyKey
Compiler !→ Runtime PayloadHash
```

Runtime도 AST/type inference를 다시 수행하지 않는다.

---

# 18. 금지 Dependency

기존 금지 규칙 유지:

```text
core → compiler/runtime/tools
ir → compiler/runtime
compiler → runtime
runtime → compiler
tools → runtime
validation → runtime
```

추가 Closure 원칙:

```text
core/ir !→ Agent Approval Workflow
core/ir !→ Policy/OA implementation
core/ir !→ NSP signature verifier implementation
core/ir !→ Runtime persistence services
```

Shared type이 필요하다는 이유로 service implementation이나 orchestration responsibility를 core/ir로 끌어올리지 않는다.

---

# 19. tools와 core/ir 경계

Tool Contract:

```text
tools/contracts.py
```

Required Tool Fingerprint:

```text
ir/schema.py
```

Write Result / WriteExecutionOutcome:

```text
tools/outcomes.py
```

Shared semantic types:

```text
core/writes.py
  ├─ PreWriteEligibility
  ├─ CommitState
  ├─ VerificationStatus
  ├─ IdempotencyKey
  └─ PayloadHash

core/ids.py
  └─ BusinessOperationId
```

단, `BusinessOperationId`, `IdempotencyKey`, `PayloadHash`의 **runtime values**는 static IR에 직렬화하지 않는다.

Write outcome은 canonical 3-way commit algebra를 유지한다.

```text
WriteCommitted
WriteNotCommitted
WriteCommitUnknown
```

`UNKNOWN_COMMIT_STATE`를 일반 ToolFailure에 숨기지 않는다.

---

# 20. Approval Service 경계

Approval 관련 shared state type은 core에 둘 수 있지만 Approval workflow는 두지 않는다.

```text
core/approvals.py
→ ApprovalStatus 등 shared semantic type

ir/
→ ApprovalStatement / ApprovalPolicy / static ApprovalId

runtime/
→ ApprovalRequest / ApprovalEvidence / ApprovalRequestId / Suspend-Resume state

Agent / Platform
→ Routing / UI / Persistence / Notification / Resume Job Scheduling
```

`ApprovalId`와 `ApprovalRequestId`를 같은 identity로 취급하지 않는다.

---

# 21. Checkpoint 경계

Checkpoint는 Runtime persistence concern이다.

```text
runtime/checkpoint.py
```

또는 실제 Repository 구조에 따라 기존 persistence/audit 영역을 재사용할 수 있다.

core/ir에는 Checkpoint service/payload implementation을 넣지 않는다.

Checkpoint가 보존할 수 있는 shared identity/value의 **타입 정의**와 actual persisted execution state를 구분한다.

```text
core
→ BusinessOperationId type

runtime checkpoint
→ actual business_operation_id value
→ approval_request_id
→ write_intent_hash / payload_hash
→ execution state
```

실제 물리 module 위치는 repository-first refactor 원칙을 따른다.

---

# 22. Versioning

```text
NSL Language 0.1
→ NSO IR 1.0

NSL Language 0.2
→ NSO IR 1.1
```

IR 1.1은 1.0의 Additive Extension이다.

Runtime 0.2는 IR 1.0과 1.1을 모두 Load해야 한다.

Source Language declaration이 authoritative하며, Compiler Option으로 임의 override하지 않는다.

v0.2 source가 WRITE를 사용하지 않더라도 Language 0.2를 선언했다면 IR 1.1 mapping을 유지한다.

---

# 23. Architecture Tests

추가 Test:

```text
compiler has no WriteExpression duplicate class
runtime has no WriteExpression duplicate class

ApprovalStatus defined in one shared semantic location
PreWriteEligibility defined in one shared semantic location
CommitState defined in one shared semantic location
VerificationStatus defined in one shared semantic location

PreWriteEligibility has no RECONCILIATION_REQUIRED
Approval↔WRITE exact 1:1 structural validation
unused Approval rejected

BusinessOperationId type may be shared but runtime value is absent from static IR
IdempotencyKey / runtime PayloadHash are absent from static IR execution identity
no embedded duplicate NSO signature requirement in semantic IR

IR 1.1 round trip
IR 1.0 backward round trip
Language 0.1 → IR 1.0
Language 0.2 → IR 1.1
v0.1 canonical Node ID / SemanticHash regression unchanged
```

Architecture test의 목적은 class/file 수를 맞추는 것이 아니라 **Single Source of Truth와 dependency boundary가 실제 코드에서 유지되는지 검증하는 것**이다.

---

# 23.1 Closure Alignment Trace

본 문서에 적용한 주요 Unified Change Ledger 항목:

```text
CHG-003  BusinessOperationId shared type / runtime-instance boundary
CHG-004  IdempotencyKey / PayloadHash 분리
CHG-007  PreWriteEligibility에서 Reconciliation 제거
CHG-010  Signed NSP Trust Boundary 재사용
CHG-011  Approval↔WRITE exactly 1:1
CHG-023  Risk Classification / PolicyDecision 분리
CHG-029  VerificationStatus typed + CommitState 분리
CHG-031  Semantic Hash / Package Integrity ownership 분리
CHG-032  Physical Package Refactor = repository-first
```

본 문서는 이 결정들을 **Shared Core / Static IR Single Source of Truth** 관점에서 구체화한다.

---

# 24. 최종 정의

> **v0.2에서도 core는 최소 공유 의미론 Kernel, ir은 Static Execution Contract다. Runtime business identity, Approval workflow, PolicyDecision, Checkpoint/Commit execution state, Package signature implementation을 core/ir로 끌어올리지 않으며, Compiler/Runtime/Tool은 동일 의미를 중복 정의하지 않는다.**
