# NeX Skill Runtime Python Interface / Protocol Detailed Design v0.2

**문서 버전:** v0.2 — Closure Aligned  
**작성일:** 2026-08-23  
**Python:** 3.12+  
**Architecture Closure 기준:** `NSL v0.2 Architecture Consistency Closure and Unified Change Ledger v1.0 — FROZEN`

---

# 1. 목적

v0.1 Python Interface를 additive하게 유지하면서 Controlled Write에 필요한 실제 Method Signature와 Dataclass를 정의한다.

본 문서는 Runtime 구현의 **Python Interface / Protocol Baseline**이며 다음 Frozen 원칙을 인터페이스 수준으로 고정한다.

```text
BusinessOperationId is runtime business identity
ApprovalId ≠ ApprovalRequestId
IdempotencyKey ≠ PayloadHash

PreWriteEligibility
≠ CommitState
≠ ExecutionStatus

Principal / DataPolicy preserved from v0.1

Approval workflow / Resume queue / Retry-Reconciliation decision
→ Agent / Platform Control Plane

Production WRITE trust
→ Signed NSP / Verified Package Trust Evidence

Provider WRITE before-call
→ durable WRITE_REQUESTED evidence

UNKNOWN_COMMIT_STATE
→ no automatic retry
```

물리 module/package 재배치는 본 문서의 목적이 아니며 실제 Repository 구조를 우선한다.

---

# 2. ExecutionRequest

신규 실행과 Resume을 구분하되 v0.1의 Security Context를 제거하지 않는다.

```python
class ExecutionMode(str, Enum):
    NEW = "NEW"
    RESUME = "RESUME"


@dataclass(frozen=True)
class ExecutionRequest:
    execution_id: ExecutionId
    business_operation_id: BusinessOperationId

    inputs: Mapping[str, object]
    runtime_context: RuntimeInputContext

    # v0.1 security context — MUST be preserved
    principal: ExecutionPrincipal
    data_policy: DataPolicy

    options: ExecutionOptions
    mode: ExecutionMode = ExecutionMode.NEW
    resume_token: ResumeToken | None = None
```

Identity 의미:

```text
execution_id
= 개별 NSL Runtime execution identity

business_operation_id
= 동일 Business WRITE를 관통하는 stable identity
  (Suspend / Resume / Re-execution / Reconciliation 동안 유지)
```

`BusinessOperationId`는 Compiler나 Static IR이 생성하지 않고 Agent/Platform에서 전달되는 Runtime request identity다.

---

# 3. ResumeToken

ResumeToken은 Platform queue 상태를 표현하지 않는다.

```python
@dataclass(frozen=True)
class ResumeToken:
    execution_id: ExecutionId
    business_operation_id: BusinessOperationId
    checkpoint_version: int
    approval_evidence: ApprovalEvidence
```

Resume 시 Runtime은 최소 다음을 검증한다.

```text
execution_id
business_operation_id
checkpoint_version
approval_evidence integrity / binding
```

`RESUME_QUEUED`는 Agent/Platform Queue State이며 이 Token이나 NSL durable ExecutionStatus의 값이 아니다.

---

# 4. ApprovalRequest

정적 Source Approval ID와 실제 승인 요청 instance ID를 분리한다.

```python
@dataclass(frozen=True)
class ApprovalRequest:
    execution_id: ExecutionId
    business_operation_id: BusinessOperationId

    approval_id: str
    approval_request_id: ApprovalRequestId

    skill_id: SkillId
    skill_version: str
    semantic_hash: str

    write_node_id: NodeId
    tool_id: ToolId

    payload_hash: PayloadHash
    write_intent_hash: str

    risk_level: RiskLevel
    message: str
    expires_at: datetime | None

    display_safe_summary: Mapping[str, object]
    protected_payload_ref: str | None
    data_classification: DataClassification
```

```text
ApprovalId
= Source / IR의 정적 Approval identity

ApprovalRequestId
= 해당 BusinessOperation에서 생성된 실제 승인 request instance
```

Approval Queue/Event/Audit에 raw WRITE Payload를 기본 복제하지 않는다. 상세 Payload가 필요하면 권한이 확인된 `protected_payload_ref`를 통해 조회한다.

---

# 5. Approval Evidence

Approval lifecycle state, human decision, evidence validation 결과를 분리한다.

```python
class ApprovalDecision(str, Enum):
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class ApprovalEvidenceValidation(str, Enum):
    VALID = "VALID"
    INVALID = "INVALID"
    EXPIRED = "EXPIRED"
    INTENT_MISMATCH = "INTENT_MISMATCH"
    PAYLOAD_MISMATCH = "PAYLOAD_MISMATCH"
    BUSINESS_OPERATION_MISMATCH = "BUSINESS_OPERATION_MISMATCH"
    APPROVAL_REQUEST_MISMATCH = "APPROVAL_REQUEST_MISMATCH"


@dataclass(frozen=True)
class ApprovalEvidence:
    execution_id: ExecutionId
    business_operation_id: BusinessOperationId

    approval_id: str
    approval_request_id: ApprovalRequestId

    skill_semantic_hash: str
    decision: ApprovalDecision

    approver_id: str
    decided_at: datetime
    expires_at: datetime | None

    payload_hash: PayloadHash
    write_intent_hash: str
    evidence_integrity: str
```

`ApprovalStatus`는 Runtime의 approval lifecycle state에 계속 사용할 수 있으나, `ApprovalEvidence.decision` 타입으로 `PENDING`/`NOT_REQUESTED` 같은 lifecycle 값을 사용하지 않는다.

Approval Evidence는 다른 `BusinessOperationId` 또는 `ApprovalRequestId`에 재사용할 수 없다.

---

# 6. ApprovalPort

Runtime은 Approval 결과를 `await`하지 않는다. Checkpoint를 durable하게 저장하고 Approval Request를 publish한 뒤 `StatementSuspended`를 반환하여 Worker를 release한다.

```python
class ApprovalPort(Protocol):

    async def publish(
        self,
        request: ApprovalRequest,
    ) -> None:
        ...
```

`publish()`는 Approval workflow를 수행한다는 의미가 아니다.

```text
NSL Runtime
→ ApprovalRequest 생성 / publish

Agent / Platform
→ Routing
→ UI / Notification
→ Persistence
→ Human Decision
→ Resume Job Scheduling
```

`ApprovalRequestId`를 기준으로 publish는 idempotent하게 구현되어야 한다.

---

# 7. ExecutionCheckpoint

Checkpoint는 Resume에 필요한 execution identity와 opaque serialized state를 보존한다.

```python
@dataclass(frozen=True)
class ExecutionCheckpoint:
    execution_id: ExecutionId
    business_operation_id: BusinessOperationId
    checkpoint_version: int

    skill_id: SkillId
    skill_version: str
    semantic_hash: str
    ir_version: str
    runtime_version: str

    state_payload: bytes
    integrity_hash: str
```

`state_payload`에는 필요에 따라 다음이 포함될 수 있다.

```text
Principal / DataPolicy binding
ApprovalRequestId
PayloadHash
WriteIntentHash
per-execution Approval State
Write Journal State
Idempotency State
Resource / Frame / Check state
```

세부 State serialization은 별도 Codec가 담당한다.

---

# 8. CheckpointPort

```python
class CheckpointPort(Protocol):

    async def save(
        self,
        checkpoint: ExecutionCheckpoint,
    ) -> None:
        ...

    async def load(
        self,
        execution_id: ExecutionId,
        checkpoint_version: int,
    ) -> ExecutionCheckpoint:
        ...
```

Approval suspend 시 순서는 다음을 만족해야 한다.

```text
WriteIntent Freeze
→ ApprovalRequestId 생성
→ CheckpointPort.save() durable success
→ ApprovalPort.publish()
→ WAITING_FOR_APPROVAL
```

Approval Request가 publish된 뒤 Checkpoint가 존재하지 않는 crash inconsistency를 허용하지 않는다.

---

# 9. WriteIntent

```python
@dataclass(frozen=True)
class WriteIntent:
    business_operation_id: BusinessOperationId

    node_id: NodeId
    tool_ref: ToolRef
    approval_id: str

    canonical_arguments: Mapping[str, ValueEnvelope]

    payload_hash: PayloadHash
    write_intent_hash: str
```

`WriteIntent`는 Runtime object다.

```text
BusinessOperationId / PayloadHash
→ Runtime invocation identity/evidence

Static IR
→ write node / tool ref / approval ref
```

Compiler가 BusinessOperationId, IdempotencyKey 또는 runtime PayloadHash를 생성해서는 안 된다.

---

# 10. WriteIntentBuilder

```python
class WriteIntentBuilder:

    def build(
        self,
        expression: WriteExpression,
        arguments: Mapping[str, ValueEnvelope],
        ctx: ExecutionContext,
    ) -> WriteIntent:
        ...
```

Builder는 Canonical Argument Serialization을 사용해 `PayloadHash`와 `write_intent_hash`를 deterministic하게 생성한다.

Approval 후 argument 변경이 필요하면 기존 Approval Evidence를 재사용하지 않고 새로운 WriteIntent / ApprovalRequest를 생성해야 한다.

---

# 11. WriteGuardRequest

WriteGuard는 WRITE 직전의 **current execution evidence**를 소비한다.

```python
@dataclass(frozen=True)
class WriteGuardRequest:
    intent: WriteIntent
    required_tool: RequiredTool

    validation: ValidationSummary
    approval_evidence: ApprovalEvidence | None
    approval_validation: ApprovalEvidenceValidation

    principal: ExecutionPrincipal
    data_policy: DataPolicy

    policy_decision: PolicyDecision
    business_preconditions: BusinessPreconditionEvidence | None
```

`BusinessPreconditionEvidence`는 version/revision, ETag/precondition token, transactional revalidation capability 등 Tool/Canonical API가 정의한 write-time freshness evidence를 나타내는 opaque typed value로 구현할 수 있다.

---

# 12. WriteGuardDecision

```python
@dataclass(frozen=True)
class WriteGuardDecision:
    eligibility: PreWriteEligibility
    reason_code: str | None
```

`PreWriteEligibility` 값:

```text
ALLOWED
BLOCKED
REQUIRES_APPROVAL
```

`RECONCILIATION_REQUIRED`는 PreWriteEligibility 값이 아니다.

---

# 13. WriteGuard

```python
class WriteGuard:

    def evaluate(
        self,
        request: WriteGuardRequest,
    ) -> WriteGuardDecision:
        ...
```

WriteGuard 책임:

```text
Required CHECK state
Approval Evidence / Intent / Payload binding
current PolicyDecision
Business Preconditions
RequiredTool fingerprint / WRITE semantics already preflighted evidence
Idempotency readiness
Replay no-live-write guard
```

WriteGuard가 담당하지 않는 것:

```text
Package signature verification implementation
Approval routing / UI
Resume queue scheduling
Retry / Reconciliation decision
```

Risk metadata의 static existence/shape 검증은 Compiler/Preflight 책임이고, User/Tenant별 current allow/deny는 `policy_decision`으로 전달받는다.

---

# 14. IdempotencyKeyFactory

`PayloadHash`를 Idempotency Key 생성 입력에 섞지 않는다.

```python
class IdempotencyKeyFactory:

    def create(
        self,
        tenant_id: TenantId,
        business_operation_id: BusinessOperationId,
        node_id: NodeId,
    ) -> IdempotencyKey:
        ...
```

논리 모델:

```text
TenantId + BusinessOperationId + WriteNodeId
→ stable IdempotencyKey

Canonical Payload
→ PayloadHash
```

동일 IdempotencyKey + 다른 PayloadHash는 Provider/Canonical API에서 `IDEMPOTENCY_CONFLICT`로 처리되어야 한다.

---

# 15. WriteCallRequest

```python
@dataclass(frozen=True)
class WriteCallRequest:
    execution_id: ExecutionId
    business_operation_id: BusinessOperationId
    invocation_id: ToolInvocationId

    node_id: NodeId
    tool_ref: ToolRef

    arguments: Mapping[str, ValueEnvelope]

    idempotency_key: IdempotencyKey
    payload_hash: PayloadHash

    approval_id: str
    approval_request_id: ApprovalRequestId
    write_intent_hash: str

    business_preconditions: BusinessPreconditionEvidence | None
    call_context: ToolCallContext
```

Identity non-collapse:

```text
BusinessOperationId
≠ execution_id
≠ invocation_id

IdempotencyKey
≠ PayloadHash
```

Provider 호출 전에 이 request의 critical identity/evidence가 durable `WRITE_REQUESTED` record로 저장되어야 한다.

---

# 16. Write Result

```python
@dataclass(frozen=True)
class WriteResultEnvelope:
    business_operation_id: BusinessOperationId

    value: object
    type_info: TypeInfo
    business_reference: str

    commit_state: CommitState

    idempotency_key: IdempotencyKey
    payload_hash: PayloadHash

    approval_request_id: ApprovalRequestId
    write_intent_hash: str

    provider_transaction_id: str | None
    committed_at: datetime | None
    metadata: Mapping[str, object]
```

Commit 결과와 Post-Write Verification 결과는 서로 다른 타입/필드로 유지한다.

---

# 17. Write Outcome

Canonical WRITE Outcome은 3-way commit algebra를 사용한다.

```python
@dataclass(frozen=True)
class WriteCommitted:
    result: WriteResultEnvelope


@dataclass(frozen=True)
class WriteNotCommitted:
    error: ToolError


@dataclass(frozen=True)
class WriteCommitUnknown:
    business_operation_id: BusinessOperationId
    invocation_id: ToolInvocationId

    tool_id: ToolId
    idempotency_key: IdempotencyKey
    payload_hash: PayloadHash

    message: str
    provider_transaction_id: str | None


WriteExecutionOutcome: TypeAlias = (
    WriteCommitted
    | WriteNotCommitted
    | WriteCommitUnknown
)
```

별도의 모호한 `WriteFailure` variant를 두어 Commit 여부를 숨기지 않는다.

```text
Committed
NotCommitted
CommitUnknown
```

중 하나를 보존해야 한다.

---

# 18. WriteExecutionPort

```python
class WriteExecutionPort(Protocol):

    async def execute(
        self,
        request: WriteCallRequest,
    ) -> WriteExecutionOutcome:
        ...
```

`WriteExecutionPort` 호출 전에는 `WRITE_REQUESTED` evidence가 durable해야 한다.

Provider 호출 후 timeout/cancellation이 발생하여 Commit 여부를 증명할 수 없다면 이를 `WriteNotCommitted` 또는 `CANCELLED`로 축소해서는 안 되고 `WriteCommitUnknown`으로 보존해야 한다.

---

# 19. RuntimePolicyPort

```python
class RuntimePolicyPort(Protocol):

    def authorize_write(
        self,
        request: WritePolicyRequest,
    ) -> PolicyDecision:
        ...
```

Policy/OA가 Tenant/User entitlement, MFA, 환경별 Risk 허용 여부를 결정한다.

Runtime Core는 Risk Policy를 하드코딩하지 않는다.

Approval 대기 중 정책이 변경될 수 있으므로 `PolicyDecision`은 WRITE 직전 WriteGuard 경로에서 현재 기준으로 재평가할 수 있어야 한다.

---

# 20. Verified Package Trust Evidence

Runtime에서 raw `SkillObject`에 대해 별도의 중복 SignatureVerifier를 두지 않는다.

Production WRITE는 NSP Package Loader/Verifier가 생성한 Trust Evidence를 소비한다.

```python
@dataclass(frozen=True)
class PackageTrustEvidence:
    package_id: str
    package_hash: str
    publisher_id: str
    signing_key_id: str
    verified_at: datetime
    trust_policy_id: str


@dataclass(frozen=True)
class VerifiedSkillArtifact:
    skill: SkillObject
    trust: PackageTrustEvidence | None
```

규칙:

```text
IR 1.0 READ-only development/test
→ trust policy에 따라 optional 가능

Production WRITE
→ Verified Signed NSP Trust Evidence REQUIRED
```

Package signature bytes, key-chain 검증, trusted publisher 확인은 NSP Package/Security Adapter에서 수행한다.

---

# 21. RuntimePorts v0.2

Provider 호출 직전/직후의 critical WRITE evidence는 durable해야 한다.

```python
@dataclass(frozen=True)
class WriteAttemptRecord:
    execution_id: ExecutionId
    business_operation_id: BusinessOperationId
    invocation_id: ToolInvocationId
    node_id: NodeId

    idempotency_key: IdempotencyKey
    payload_hash: PayloadHash
    write_intent_hash: str
    approval_request_id: ApprovalRequestId


class WriteEvidencePort(Protocol):

    async def record_requested(
        self,
        record: WriteAttemptRecord,
    ) -> None:
        ...

    async def record_outcome(
        self,
        record: WriteAttemptRecord,
        outcome: WriteExecutionOutcome,
    ) -> None:
        ...


@dataclass(frozen=True)
class RuntimePorts:
    read_tools: ToolExecutionPort
    write_tools: WriteExecutionPort

    approvals: ApprovalPort
    checkpoints: CheckpointPort

    # Durable WRITE_REQUESTED / outcome evidence.
    # 구현상 Checkpoint repository와 같은 storage를 사용할 수 있으나
    # logical durability contract는 분리한다.
    write_evidence: WriteEvidencePort

    trace: TraceSink
    provenance: ProvenanceStore
    clock: RuntimeClock
    cancellation: CancellationToken

    policy: RuntimePolicyPort
```

`SignatureVerifier`는 RuntimePorts에서 제거한다.

Verified Signed NSP trust verification은 Runtime 호출 이전 Package Boundary에서 수행되고 RuntimePreflight는 `VerifiedSkillArtifact.trust`를 확인한다.

---

# 22. RuntimePreflightValidator

```python
class RuntimePreflightValidator:

    def validate(
        self,
        artifact: VerifiedSkillArtifact,
        request: ExecutionRequest,
        tool_catalog: ToolContractCatalog,
    ) -> PreflightReport:
        ...
```

Preflight 책임:

```text
IR / Language feature support
Semantic hash / artifact consistency
Verified Package Trust Evidence requirement
RequiredTool / current Tool Contract fingerprint compatibility
WRITE capability
Atomicity
Idempotency support
Runtime port / feature availability
Principal / DataPolicy structural presence
```

Preflight가 담당하지 않는 것:

```text
Current Tenant/User Risk allow/deny
Approval Evidence decision
Write-time Business Preconditions
IdempotencyKey generation
Retry / Reconciliation decision
```

위 current execution decision은 WriteGuard/Agent-Platform 경계에서 처리한다.

---

# 23. StatementExecutor v0.2

기존 Signature를 additive하게 유지한다.

```python
async def execute(
    self,
    statement: Statement,
    ctx: ExecutionContext,
    ports: RuntimePorts,
) -> StatementExecution:
    ...
```

```python
StatementExecution: TypeAlias = (
    StatementContinued
    | StatementSuspended
)
```

`ApprovalStatement`는 Approval workflow 결과를 기다리는 것이 아니라 Checkpoint/Publish를 완료한 뒤 `StatementSuspended`를 반환한다.

---

# 24. Suspension

```python
@dataclass(frozen=True)
class StatementSuspended:
    reason: str
    checkpoint_version: int
    approval_id: str
    approval_request_id: ApprovalRequestId
```

Approval suspend의 Runtime durable status는 `WAITING_FOR_APPROVAL`이다.

```text
RESUME_QUEUED
→ Platform queue state

WRITE_IN_PROGRESS
→ internal write-attempt state / audit event
```

두 값을 public durable `ExecutionStatus`로 추가하지 않는다.

---

# 25. ExpressionEvaluator v0.2

READ/ordinary expression의 성공 결과는 기존 `ValueEnvelope`를 유지한다.

WRITE는 Commit outcome을 먼저 보존한 뒤 `COMMITTED`일 때만 ValueEnvelope로 binding할 수 있다.

```python
async def evaluate(
    self,
    expression: Expression,
    ctx: ExecutionContext,
    ports: RuntimePorts,
) -> ValueEnvelope:
    ...
```

WriteExpression 내부 canonical flow:

```text
arguments
→ WriteIntent / PayloadHash
→ WriteGuard
→ IdempotencyKey
→ durable WRITE_REQUESTED
→ WriteExecutionPort
→ WriteExecutionOutcome
```

규칙:

```text
WriteCommitted
→ WriteResultEnvelope
→ Provenance
→ ValueEnvelope binding 가능

WriteNotCommitted
→ normal success ValueEnvelope 생성 금지

WriteCommitUnknown
→ normal success ValueEnvelope 생성 금지
→ RECONCILIATION_REQUIRED
```

구현에서는 `WriteNotCommitted`/`WriteCommitUnknown`을 RuntimeEngine이 구조화된 terminal/disposition 결과로 처리할 수 있도록 내부 control result 또는 typed signal을 사용할 수 있다. Commit uncertainty를 일반 값이나 generic ToolFailure로 숨겨서는 안 된다.

---

# 26. ApprovalCoordinator

```python
class ApprovalCoordinator:

    async def request_and_suspend(
        self,
        statement: ApprovalStatement,
        linked_write: WriteExpression,
        ctx: ExecutionContext,
        ports: RuntimePorts,
    ) -> StatementSuspended:
        ...
```

반드시 다음 순서를 보장한다.

```text
1. WriteIntent Freeze
2. ApprovalRequestId 생성
3. ExecutionCheckpoint 생성
4. CheckpointPort.save() durable success
5. ApprovalPort.publish()  # ApprovalRequestId 기반 idempotent
6. ctx.status = WAITING_FOR_APPROVAL
7. StatementSuspended 반환
```

ApprovalCoordinator는 승인자를 선택하거나 UI/Notification/Resume Queue를 orchestrate하지 않는다.

---

# 27. CheckpointCoordinator

```python
class CheckpointCoordinator:

    async def save(
        self,
        ctx: ExecutionContext,
        ports: RuntimePorts,
    ) -> ExecutionCheckpoint:
        ...

    async def restore(
        self,
        checkpoint: ExecutionCheckpoint,
        artifact: VerifiedSkillArtifact,
    ) -> ExecutionContext:
        ...
```

Restore는 최소 다음 binding을 검증할 수 있어야 한다.

```text
execution_id
business_operation_id
semantic_hash
IR/runtime version compatibility
Principal / DataPolicy
checkpoint integrity
```

Resume Approval Evidence 검증은 별도 Resume/Approval validation 단계에서 수행한다.

---

# 28. PostWriteVerifier

```python
class PostWriteVerifier:

    async def verify(
        self,
        result: WriteResultEnvelope,
        contract: ToolContract,
        ctx: ExecutionContext,
        ports: RuntimePorts,
    ) -> VerificationResult:
        ...
```

`VerificationResult.status`는 typed `VerificationStatus`를 사용한다.

```text
NOT_REQUESTED
VERIFIED
FAILED
UNKNOWN
```

Verification이 FAILED/UNKNOWN이어도 이미 `COMMITTED`인 CommitState를 `NOT_COMMITTED`로 재분류해서는 안 된다.

---

# 29. ExecutionResult v0.2

v0.2 Result는 v0.1 Result Contract를 대체하지 않고 additive하게 확장한다.

```python
@dataclass(frozen=True)
class ExecutionResult:
    execution_id: ExecutionId
    skill_id: SkillId
    skill_version: str
    semantic_hash: str

    status: ExecutionStatus
    validation: ValidationSummary

    outputs: tuple[EmitRecord, ...]
    resources: ResourceUsage
    error: RuntimeErrorInfo | None

    # v0.2 additive fields
    pre_write_eligibility: PreWriteEligibility | None = None
    approval: ApprovalSummary | None = None
    write: WriteSummary | None = None
    verification: VerificationSummary | None = None
    suspension: SuspensionInfo | None = None
```

READ-only IR 1.0 실행에서는 WRITE 관련 optional field가 `None`/Not Applicable일 수 있다.

`ExecutionStatus`는 v0.1의 다음 값을 보존한다.

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

v0.2 durable 추가 상태:

```text
WAITING_FOR_APPROVAL
RECONCILIATION_REQUIRED
```

---

# 30. RuntimeEngine

```python
class RuntimeEngine:

    async def execute(
        self,
        artifact: VerifiedSkillArtifact,
        request: ExecutionRequest,
        ports: RuntimePorts,
    ) -> ExecutionResult:
        ...
```

`request.mode`에 따라 NEW/RESUME 경로를 처리한다.

v0.1 read-only 호출 호환성을 위해 기존 `SkillObject` 입력을 받는 adapter를 둘 수 있으나 Production WRITE canonical path는 `VerifiedSkillArtifact`를 사용한다.

RuntimeEngine은 다음을 하지 않는다.

```text
Approval Workflow orchestration
Resume Job scheduling
Package Signature verification implementation
Retry / Reconciliation decision
```

해당 기능은 각각 Platform / NSP Package Boundary의 책임이다.

---

# 31. NEW 실행

```text
VerifiedSkillArtifact
→ RuntimePreflight
→ ExecutionContext create
   (Principal / DataPolicy / BusinessOperationId)
→ execute READ / CHECK
→ PreWriteEligibility
→ WriteIntent / PayloadHash
→ ApprovalRequestId
→ Checkpoint durable save
→ Approval Request idempotent publish
→ WAITING_FOR_APPROVAL result
```

CHECK가 FAIL/UNKNOWN이면 Approval-to-WRITE transition을 시작하지 않고 BLOCKED로 종료한다.

---

# 32. RESUME 실행

```text
checkpoint load
→ checkpoint integrity
→ execution_id / BusinessOperationId binding
→ artifact semantic hash / trust evidence
→ Principal / DataPolicy restore/validate
→ ApprovalEvidence integrity
→ ApprovalRequestId binding
→ PayloadHash / WriteIntentHash
→ context restore
→ current PolicyDecision
→ write-time Business Preconditions
→ WriteGuard
→ IdempotencyKey
→ durable WRITE_REQUESTED
→ WriteExecutionPort
```

Approval이 REJECTED/EXPIRED/INVALID이면 WRITE하지 않는다.

Resume scheduling 자체는 Agent/Platform의 책임이다.

---

# 33. UNKNOWN Commit / Cancellation / Timeout

```python
if isinstance(outcome, WriteCommitUnknown):
    ctx.status = ExecutionStatus.RECONCILIATION_REQUIRED
    ...
```

`WriteCommitUnknown`에서는 정상 ValueEnvelope을 생성하지 않는다.

Cancellation/Timeout 규칙:

```text
Provider가 호출되지 않았음이 확실
→ CANCELLED / NOT_COMMITTED 가능

Provider 호출 이후 Commit 여부 불명
→ UNKNOWN_COMMIT_STATE
→ RECONCILIATION_REQUIRED
```

Runtime은 UNKNOWN Commit에서 새 WRITE를 자동 Retry하지 않는다.

Runtime Result는 `BusinessOperationId`, `IdempotencyKey`, `PayloadHash`, `ToolInvocationId`, provider transaction reference 등 Reconciliation에 필요한 evidence를 구조화해 반환한다.

어떤 Reconciliation Action을 선택할지는 Agent/Platform이 결정한다.

---

# 34. Mock / Replay

```python
class MockWriteExecutor(WriteExecutionPort):
    ...


class ReplayWriteExecutor(WriteExecutionPort):
    ...
```

Replay는 WRITE Snapshot만 재사용하는 것으로 충분하지 않다.

Replay execution에 영향을 주는 다음 evidence도 snapshot/replay adapter를 통해 고정한다.

```text
Approval Evidence
Policy Decision
Verified Package / Trust Evidence
Write Outcome
Verification Outcome
```

규칙:

> **Replay = no live control-plane decision calls + no live WRITE**

현재 Approval/Policy Service를 재호출하여 과거 실행의 의미를 변경해서는 안 된다.

---

# 35. Testing Ports

권장 Test Double:

```text
MemoryApprovalPort
MemoryCheckpointPort
MemoryWriteEvidencePort

MockWriteExecutor
ReplayWriteExecutor

FakeRuntimePolicyPort
FakeClock

VerifiedTestSkillArtifact
ReplayApprovalEvidenceProvider
ReplayPolicyEvidenceProvider
```

별도의 `FakeSignatureVerifier`를 RuntimePorts에 둘 필요는 없다. Package trust 검증은 VerifiedSkillArtifact fixture/evidence로 테스트한다.

필수 Safety Test에는 다음이 포함되어야 한다.

```text
Principal/DataPolicy preserved on NEW/RESUME
BusinessOperationId stable across resume
ApprovalRequestId binding mismatch
PayloadHash mismatch
IdempotencyKey stable while PayloadHash separate
checkpoint-before-approval-publish
durable WRITE_REQUESTED before provider call
cancellation/timeout → CommitUnknown when uncertain
VALIDATION_ERROR backward compatibility
replay no-live-policy/approval/write
```

---

# 36. 핵심 Interface Baseline

```text
RuntimeEngine.execute()

ApprovalCoordinator.request_and_suspend()
CheckpointCoordinator.save()/restore()

WriteIntentBuilder.build()
WriteGuard.evaluate()

IdempotencyKeyFactory.create()

WriteEvidencePort.record_requested()/record_outcome()
WriteExecutionPort.execute()

PostWriteVerifier.verify()
RuntimePreflightValidator.validate()
```

Identity/Data boundary:

```text
ExecutionRequest
  ├─ execution_id
  ├─ BusinessOperationId
  ├─ Principal
  └─ DataPolicy

ApprovalRequest / Evidence
  ├─ ApprovalId
  ├─ ApprovalRequestId
  ├─ BusinessOperationId
  ├─ PayloadHash
  └─ WriteIntentHash

WriteCallRequest
  ├─ execution_id
  ├─ BusinessOperationId
  ├─ ToolInvocationId
  ├─ IdempotencyKey
  └─ PayloadHash
```

`WriteEvidencePort`는 logical durability contract다. 실제 구현에서 Checkpoint/Event Repository와 같은 persistence를 재사용할 수 있으며, 본 문서는 물리 package 구조를 강제하지 않는다.

---

# 36.1 Closure Alignment Trace

본 문서에 적용한 주요 Unified Change Ledger 항목:

```text
CHG-002  Python 3.12+
CHG-003  BusinessOperationId Runtime Contract
CHG-004  IdempotencyKey / PayloadHash 분리
CHG-005  ApprovalRequestId + Evidence Binding
CHG-006  Approval Workflow Ownership → Agent/Platform
CHG-008  Runtime ExecutionStatus 정리
CHG-009  Principal / DataPolicy 보존
CHG-010  Signed NSP / Verified Package Trust 재사용
CHG-017  Write-time Business Preconditions
CHG-018  Checkpoint → Approval Publish Crash Consistency
CHG-019  Provider 호출 전 durable WRITE_REQUESTED
CHG-020  Cancellation / Timeout Commit Uncertainty
CHG-021  RuntimePreflight / WriteGuard 책임 분리
CHG-022  WriteOutcome 3-way Algebra
CHG-024  Approval Payload Protected Reference
CHG-025  Replay Control-Evidence Snapshot
CHG-027  ExecutionContext State-only / Ports Boundary
CHG-028  Approval Status / Decision / Evidence Validation 분리
CHG-029  VerificationStatus typed + Commit 분리
CHG-030  ExecutionResult additive compatibility
CHG-032  Repository-first physical refactor
```

본 문서는 위 Frozen 결정을 Python Dataclass / Protocol / Method Signature 수준으로 구체화한다.

---

# 37. 최종 정의

> **v0.2 Python Interface는 Approval 대기를 Worker I/O 대기가 아니라 Checkpoint 기반 Suspend/Resume Protocol로 모델링하고, BusinessOperationId·ApprovalRequestId·IdempotencyKey·PayloadHash를 분리한다. WRITE는 durable pre-call evidence와 3-way Commit Outcome으로 격리하며, Commit 불확실성·Approval/Policy/Trust evidence·v0.1 Security Context를 타입과 Protocol 경계에서 보존한다.**
