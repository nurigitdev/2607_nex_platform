# NeX Skill Language Compiler Python Class / Interface Detailed Design v0.2

**문서 버전:** v0.2 — Closure Aligned  
**작성일:** 2026-08-23  
**대상:** NSL v0.2 Compiler Python 구현  
**Architecture Closure 기준:** `NSL v0.2 Architecture Consistency Closure and Unified Change Ledger v1.0 — FROZEN`

---

# 1. 목적

v0.1 Class/Interface 구조와 deterministic compiler behavior를 유지하면서 Approval/Write 관련 AST, Symbol, Static Analysis, Lowering Interface를 **additive하게** 확장한다.

본 문서의 Compiler 경계는 다음과 같다.

```text
Source / AST
  ↓
Name / Tool / Type Resolution
  ↓
Static Write Safety Proof
  ↓
Canonical IR 1.0 / 1.1
  ↓
SemanticHash / SourceBundleHash
```

Compiler는 다음 Runtime/Control Plane identity 또는 decision을 생성하지 않는다.

```text
BusinessOperationId
ApprovalRequestId
IdempotencyKey
Runtime PayloadHash
PolicyDecision
CommitState
Reconciliation decision
```

Production signing 역시 Compiler Core의 책임이 아니다. Compiler는 canonical NSO와 semantic/source-bundle hash를 생성하고, Signed NSP build/signing은 별도 Package Pipeline이 담당한다.

---

# 2. AST

v0.2 AST는 Approval/Write syntax를 additive하게 표현한다.

```python
@dataclass(frozen=True, slots=True)
class ApproveStatementAst:
    node_id: AstNodeId
    span: SourceSpan
    approval_id: str
    message: str
```

```python
@dataclass(frozen=True, slots=True)
class WriteExpressionAst:
    node_id: AstNodeId
    span: SourceSpan
    tool_name: QualifiedName
    arguments: tuple[ArgumentAst, ...]
    approval_id: str
```

`ExpressionAst` Union에 `WriteExpressionAst`를, `StatementAst`에 `ApproveStatementAst`를 추가한다.

중요한 Backward Compatibility Rule:

```text
Source Language 0.1
→ 기존 keyword set / identifier semantics 유지

Source Language 0.2
→ write / approve / approved_by keyword 활성화
```

Parser/Lexer는 Source에 선언된 Language Version을 authoritative하게 사용해야 한다. Compiler Option이 Source Language Version을 임의 override해서는 안 된다.

---

# 3. Approval Symbol

```python
@dataclass(frozen=True, slots=True)
class ApprovalSymbol:
    approval_id: str
    declaration_node_id: AstNodeId
    declaration_span: SourceSpan
    declaration_order: int
```

`ApprovalSymbol`은 Source/Compiler의 **정적 Approval identity**를 나타낸다.

실제 실행마다 생성되는 `ApprovalRequestId`와 동일한 식별자가 아니며 Compiler가 ApprovalRequestId를 생성하거나 IR에 기록해서는 안 된다.

---

# 4. DeclarationIndex v0.2

```python
@dataclass(frozen=True)
class DeclarationIndex:
    value_declarations: Mapping[str, ValueDeclaration]
    check_declarations: Mapping[str, CheckDeclaration]
    tool_declarations: Mapping[str, ToolDeclaration]
    type_declarations: Mapping[str, TypeDeclaration]
    approval_declarations: Mapping[str, ApprovalDeclaration]
```

v0.1 declaration index를 additive하게 확장한다.

`approval_declarations`는 duplicate Approval ID와 unused Approval 검증을 위한 static source of truth로 사용한다.

---

# 5. NameResolution v0.2

```python
@dataclass(frozen=True)
class NameResolution:
    symbols: Mapping[AstNodeId, ValueSymbol]
    checks: Mapping[AstNodeId, CheckSymbol]
    approvals: Mapping[AstNodeId, ApprovalSymbol]
    scopes: Mapping[AstNodeId, ScopeInfo]
```

`approved_by` / approval reference는 반드시 `ApprovalSymbol`로 resolve되어야 한다.

NameResolver는 static reference/declaration order를 제공하되 실제 승인자, 승인 상태, Approval workflow를 결정하지 않는다.

---

# 6. ToolResolution v0.2

```python
@dataclass(frozen=True)
class ResolvedToolRequirement:
    tool_ref: ToolRef
    tool_id: ToolId
    tool_version: str
    capability: ToolCapability
    risk_level: RiskLevel
    contract_hash: str
    contract: ToolContract
```

Compiler가 확인하는 것은 Tool의 **static semantic contract**다.

```text
capability
operation kind
atomicity
idempotency support
risk classification metadata
contract hash
```

Compiler는 다음을 결정하지 않는다.

```text
Tenant/User WRITE entitlement
MFA requirement
current PolicyDecision
runtime Business Preconditions
```

RiskLevel은 static classification metadata이고 실제 allow/deny는 Runtime에서 external Policy/OA evidence로 확인한다.

---

# 7. TypeChecker

기존 Public Signature를 유지할 수 있다.

```python
class TypeChecker:
    def check(
        self,
        ast: ComposedSkillAst,
        names: NameResolution,
        tools: ToolResolution,
        contexts: ContextSchema,
        builtins: BuiltinSignatureRegistry,
        diagnostics: DiagnosticSink,
    ) -> TypeAnalysis:
        ...
```

v0.2 내부 확장:

```python
def _check_write_expression(
    self,
    expression: WriteExpressionAst,
    ...
) -> TypeInfo:
    ...
```

책임:

```text
WRITE argument type compatibility
WRITE result type compatibility
Money / Decimal / Currency semantics
no runtime type inference dependency
```

TypeChecker는 side-effect permission 또는 business policy를 판정하지 않는다.

---

# 8. WriteSafetyAnalysis

`WriteSafetyAnalysis`는 Compile-time Safety Proof 결과다.

```python
@dataclass(frozen=True)
class WriteSafetyAnalysis:
    write_node_count: int
    approval_node_count: int

    approval_write_mapping_count: int
    unused_approval_count: int

    max_write_calls: int
    writes_inside_loop: bool

    all_writes_approved_exactly_once: bool
    all_write_operations_supported: bool
    all_write_tools_atomic: bool
    all_write_tools_idempotent: bool
    all_write_risk_metadata_present: bool

    requires_verified_package_for_write: bool
```

`requires_verified_package_for_write`는 Compiler가 signing을 수행한다는 뜻이 아니다.

의미:

```text
WRITE-bearing Skill
→ Production execution requires Verified Signed NSP trust evidence
```

`BusinessOperationId`, `IdempotencyKey`, runtime `PayloadHash`는 이 분석 결과에 포함하지 않는다.

---

# 9. WriteSafetyAnalyzer

```python
class WriteSafetyAnalyzer:

    def analyze(
        self,
        ast: ComposedSkillAst,
        names: NameResolution,
        tools: ToolResolution,
        types: TypeAnalysis,
        profile: SemanticsProfile,
        diagnostics: DiagnosticSink,
    ) -> WriteSafetyAnalysis:
        ...
```

`NSL-0.2-STRICT`에서 검증하는 정적 조건:

```text
write count <= 1
WRITE not inside FOREACH

Approval ref exists
Approval declared before WRITE
Approval ↔ WRITE exactly 1:1
unused Approval == 0

Tool capability == WRITE
operation kind supported
atomicity == ATOMIC
idempotency supported
risk metadata present / valid

all WRITE arguments statically typed
no dynamic WRITE tool
```

Safety-critical 규칙은 `CompilerOptions`로 완화하지 않는다.

Compiler가 하지 않는 일:

```text
Risk entitlement decision
Approval workflow decision
BusinessOperationId generation
IdempotencyKey generation
Retry / Reconciliation decision
```

---

# 10. SemanticModel v0.2

```python
@dataclass(frozen=True)
class SemanticModel:
    names: NameResolution
    tools: ToolResolution
    types: TypeAnalysis
    safety: SafetyReport
    write_safety: WriteSafetyAnalysis
    resource_bounds: ResourceBounds
    source_bundle: SourceBundleModel
```

`SemanticModel`은 Source → IR lowering에 필요한 compile-time evidence만 포함한다.

Runtime invocation identity나 mutable execution state를 포함하지 않는다.

---

# 11. Deterministic IR Node Allocator

v0.1의 기존 deterministic allocator를 **확장**한다.

```python
class DeterministicIrNodeAllocator:

    def approval(self) -> NodeId:
        ...

    def write(self) -> NodeId:
        ...
```

예:

```text
approval0001
write0001
```

중요한 Compatibility Rule:

```text
v0.1 source
→ 기존 NodeId allocation sequence 불변
→ canonical IR 불변
→ SemanticHash 불변
```

v0.2 node type 추가를 이유로 기존 allocator를 새 병렬 allocator로 교체하거나, v0.1 node numbering을 이동시키면 안 된다.

---

# 12. Lowerer

기존 Public Signature를 최대한 유지한다.

```python
class Lowerer:

    def lower(
        self,
        ast: ComposedSkillAst,
        semantic: SemanticModel,
        options: CompilerOptions,
        diagnostics: DiagnosticSink,
    ) -> SkillObject | None:
        ...
```

추가 내부:

```python
def _lower_approval(
    self,
    node: ApproveStatementAst,
    ctx: LoweringContext,
) -> ApprovalStatement:
    ...
```

```python
def _lower_write(
    self,
    node: WriteExpressionAst,
    ctx: LoweringContext,
) -> WriteExpression:
    ...
```

IR Version은 Source Language Version에 deterministic하게 매핑한다.

```text
NSL 0.1 → IR 1.0
NSL 0.2 → IR 1.1
```

Write-less NSL 0.2 source도 IR 1.1로 Lowering한다.

Lowerer는 다음 runtime values를 생성하지 않는다.

```text
BusinessOperationId
ApprovalRequestId
IdempotencyKey
runtime PayloadHash
CommitState
```

---

# 13. Tool Contract View

Compiler가 Runtime 전체 구현을 의존하지 않도록 read-only Contract View를 **필요한 경우에만** 도입할 수 있다.

```python
class CompilerToolContractView(Protocol):

    @property
    def capability(self) -> ToolCapability:
        ...

    @property
    def risk_level(self) -> RiskLevel:
        ...

    @property
    def operation_kind(self) -> OperationKind:
        ...

    @property
    def atomicity(self) -> Atomicity:
        ...

    @property
    def idempotency_required(self) -> bool:
        ...
```

중요 원칙:

```text
OperationKind / Atomicity
→ raw str이 아니라 shared typed bounded model 사용

CompilerToolContractView
→ 실제 dependency coupling 문제가 있을 때만 도입
→ architecture를 맞추기 위한 의무적 wrapper가 아님
```

기존 `ToolContract`를 직접 사용해도 dependency rule과 testability가 만족되면 허용한다.

---

# 14. CompilerServices v0.2

다음은 **logical responsibility model**이다.

```python
@dataclass(frozen=True)
class CompilerServices:
    lexer: Lexer
    parser: Parser
    bundle_builder: SourceBundleBuilder
    composer: SourceComposer
    declarations: DeclarationCollector
    names: NameResolver
    tool_resolver: ToolContractResolver
    type_checker: TypeChecker
    semantic_validator: SemanticValidator
    safety: SafetyAnalyzer
    write_safety: WriteSafetyAnalyzer
    resources: ResourceBoundAnalyzer
    lowerer: Lowerer
    ir_validator: IrValidator
    serializer: CanonicalNsoSerializer
```

이 목록이 곧 13개의 신규 physical class/module을 만들라는 요구는 아니다.

```text
Repository-first refactor
→ 실제 v0.1 구조 확인
→ dependency / complexity hotspot만 선택적으로 분리
→ 문서 예시를 맞추기 위한 big-bang package reorganization 금지
```

---

# 15. CompilerOptions v0.2

Compiler Option은 Build/Diagnostics/Resource 한계를 제공할 수 있지만 **Source Language Version이나 Safety Invariant를 override해서는 안 된다.**

권장:

```python
@dataclass(frozen=True)
class CompilerOptions:
    supported_language_versions: tuple[str, ...] = ("0.1", "0.2")
    semantics_profile: str = "NSL-0.2-STRICT"

    warnings_as_errors: bool = False
    debug_metadata: bool = True

    max_include_depth: int = 16
    max_include_files: int = 100
    max_total_source_bytes: int = 10 * 1024 * 1024
```

다음 option은 제거한다.

```text
language_version = "0.2"        # Source declaration이 authoritative
max_write_nodes = 1             # Strict Profile invariant
allow_write_in_foreach = False  # Strict Profile invariant
```

`NSL-0.2-STRICT`는 다음을 immutable하게 고정한다.

```text
write_node_count <= 1
WRITE inside FOREACH = forbidden
Approval ↔ WRITE = exactly 1:1
unused Approval = forbidden
```

---

# 16. NslCompiler.compile Pipeline

권장 pipeline:

```python
def compile(...):
    diagnostics = DiagnosticBag()

    bundle = bundle_builder.build(...)
    ast = composer.compose(...)

    source_language = ast.language_version
    validate_supported_language(source_language, options)

    declarations = declaration_collector.collect(...)
    names = name_resolver.resolve(...)
    tools = tool_resolver.resolve(...)
    types = type_checker.check(...)

    semantic_validation = semantic_validator.validate(...)
    safety = safety_analyzer.analyze(...)
    write_safety = write_safety_analyzer.analyze(...)
    bounds = resource_bound_analyzer.analyze(...)

    if diagnostics.has_errors():
        return CompilationFailure(...)

    semantic = SemanticModel(...)

    ir_version = map_language_to_ir(source_language)
    skill = lowerer.lower(..., ir_version=ir_version)

    ir_validator.validate(skill)
    artifact = serializer.serialize(...)

    return CompilationSuccess(...)
```

deterministic mapping:

```text
"0.1" → "1.0"
"0.2" → "1.1"
```

Compiler Core pipeline에는 Package signing 단계를 넣지 않는다.

---

# 17. CompilationSuccess v0.2

기존 결과를 additive하게 유지한다.

```python
@dataclass(frozen=True)
class CompilationSuccess:
    skill: SkillObject
    nso_bytes: bytes
    semantic_hash: str
    source_bundle_hash: str
    diagnostics: tuple[Diagnostic, ...]
```

필요하면 `ir_version`은 `SkillObject`에서 읽거나 additive field로 노출할 수 있다.

Hash ownership:

```text
source_bundle_hash
→ source/build identity

semantic_hash
→ canonical semantic IR identity

NSP package/artifact integrity hash
→ package layer responsibility
```

Compiler Result에 package signature identity를 혼합하지 않는다.

---

# 18. Package Signing Boundary

`NsoArtifactSigner`를 Compiler Core interface baseline에서 제거한다.

Production Trust는 기존 Signed NSP pipeline을 재사용한다.

```text
Compiler
  Canonical NSO
  SemanticHash
  SourceBundleHash
       ↓
NSP Build / Packaging
       ↓
Package Integrity Hash
       ↓
Publisher Signature
       ↓
Verified Signed NSP
```

따라서 Compiler Python package에 다음 별도 Port를 필수로 두지 않는다.

```text
NsoArtifactSigner
SignedNsoArtifact
embedded per-NSO signing path
```

필요한 crypto/signing adapter와 key management는 NSP Package Build/Security 영역에서 구현한다.

---

# 19. Diagnostic

v0.2 추가 권장 Diagnostic:

```text
NSL-E5101 UNSUPPORTED_LANGUAGE_VERSION

NSL-E5201 WRITE_IN_FOREACH
NSL-E5202 TOO_MANY_WRITES

NSL-E5301 UNKNOWN_APPROVAL
NSL-E5302 APPROVAL_ORDER
NSL-E5303 APPROVAL_WRITE_NOT_ONE_TO_ONE
NSL-E5304 UNUSED_APPROVAL

NSL-E5401 WRITE_CAPABILITY_REQUIRED
NSL-E5402 WRITE_ATOMICITY_REQUIRED
NSL-E5403 IDEMPOTENCY_REQUIRED
NSL-E5404 UNSUPPORTED_WRITE_OPERATION
NSL-E5405 WRITE_RISK_METADATA_REQUIRED
```

Diagnostic code는 deterministic해야 하며 동일 Source/Contract/Profile 입력에 대해 동일 오류 집합과 안정적인 source span을 반환해야 한다.

---

# 20. Unit Test Boundary

```text
Lexer/Parser:
  syntax + language-version-aware keyword compatibility

NameResolver:
  approval refs / declaration order / duplicate IDs

ToolResolver:
  capability / typed operation kind / atomicity / idempotency / risk metadata

TypeChecker:
  write args/result

WriteSafetyAnalyzer:
  max one write
  no foreach write
  exact Approval↔WRITE 1:1
  unused approval
  operation/capability/atomicity/idempotency/risk

Lowerer:
  NSL 0.1 → IR 1.0
  NSL 0.2 → IR 1.1

IrValidator:
  structural invariants

Determinism Regression:
  v0.1 NodeIds unchanged
  v0.1 canonical NSO unchanged
  v0.1 SemanticHash unchanged

Compiler Boundary:
  no BusinessOperationId
  no ApprovalRequestId
  no IdempotencyKey
  no runtime PayloadHash
  no NsoArtifactSigner dependency
```

NSP signing/verification crypto test는 Compiler Unit Test boundary가 아니라 Package/Security test boundary에서 수행한다.

---

# 21. Backward Compatibility

모든 v0.1 Compiler Test를 그대로 통과해야 한다.

`WriteSafetyAnalyzer`는 WRITE Node가 0개이면 정상적인 no-op analysis 결과를 생성한다.

추가 Compatibility Rules:

```text
v0.1 Source keyword/identifier semantics 유지
v0.1 Language → IR 1.0
v0.1 Node ID allocation 불변
v0.1 canonical serialization 불변
v0.1 SemanticHash 불변

v0.2 Language → IR 1.1
write-less v0.2 source도 IR 1.1
```

새 WRITE syntax 지원 때문에 기존 v0.1 artifact identity가 변하면 regression failure로 취급한다.

---

# 22. 핵심 Interface Baseline

```text
Parser.parse()
NameResolver.resolve()
ToolContractResolver.resolve()
TypeChecker.check()
WriteSafetyAnalyzer.analyze()
ResourceBoundAnalyzer.analyze()
Lowerer.lower()
IrValidator.validate()
NslCompiler.compile()
```

Compiler Core baseline에서 제거:

```text
NsoArtifactSigner.sign()
```

Runtime/Control Plane에서 생성되는 다음 interface도 Compiler baseline에 포함하지 않는다.

```text
BusinessOperationIdFactory
ApprovalRequestFactory
IdempotencyKeyFactory
PolicyDecision
Retry/Reconciliation Orchestrator
```

---

# 22.1 Closure Alignment Trace

본 문서에 적용한 주요 Unified Change Ledger 항목:

```text
CHG-010  Signed NSP Trust Boundary 재사용
CHG-011  Approval↔WRITE exactly 1:1
CHG-012  Language-version-aware Keywords
CHG-013  Safety Options → Strict Profile Immutable Rules
CHG-014  Language Version → IR Version deterministic mapping
CHG-015  Deterministic Node ID / SemanticHash 보존
CHG-023  Risk Classification / PolicyDecision 분리
CHG-031  SemanticHash / Package Integrity ownership 분리
CHG-032  Physical Package Refactor = repository-first
```

Batch B Frozen boundary에 따라 Compiler는 **Static Proof + Canonical IR 생성**까지만 소유한다. Runtime business identity, Approval workflow, Policy authorization, commit/reconciliation, package signing은 Compiler 책임이 아니다.

---

# 23. 최종 정의

> **v0.2 Compiler Python 구조는 v0.1 deterministic compiler를 additive하게 확장하여, Source/Tool/Type/Approval 관계와 WRITE Safety를 Compile-time에 정적으로 증명하고 Language 0.1→IR 1.0, Language 0.2→IR 1.1을 canonical하게 생성한다. Runtime business identity·Policy·Approval workflow·Commit/Reconciliation·Package Signing은 Compiler 경계 밖에 둔다.**
