# NeX Skill Runtime Class/Object Model Detailed Design v0.2

**문서 버전:** v0.2 — Closure Aligned  
**작성일:** 2026-08-23  
**Architecture Closure 기준:** `NSL v0.2 Architecture Consistency Closure and Unified Change Ledger v1.0 — FROZEN`

---

# 1. 목적

v0.1의 Passive IR / Stateless RuntimeEngine / Port-based Infrastructure 원칙을 유지하면서 Approval, Suspend/Resume, WriteGuard, BusinessOperationId 기반 Idempotency, Commit/Verification 객체를 추가한다.

본 문서의 Runtime은 **Deterministic Skill Execution Plane**이며 다음 Control Plane 책임을 소유하지 않는다.

```text
Approval Routing / UI / Notification
Resume Job Scheduling / Queue ownership
Retry Decision
Reconciliation Action Selection
Tenant/User Policy authoring
```

위 기능은 Agent/Platform이 담당하고, Runtime은 해당 기능에 필요한 Request/Evidence/State Contract만 제공한다.

Production WRITE의 Trust는 기존 **Signed NSP → Verified Package / Verified Skill Trust Evidence** 경계를 재사용한다.

---

# 2. Class 분류

## Immutable Value Objects

```text
SkillObject
ValueEnvelope
ApprovalRecord
ApprovalRequest
ApprovalEvidence
WriteIntent
WriteAttemptRecord
WriteJournalEntry
ToolContract
WriteResultEnvelope
ExecutionCheckpoint
PackageTrustEvidence
```

## Per-Execution Mutable State

```text
ExecutionContext
FrameStack
CheckStore
EmitBuffer
ResourceMeter
ApprovalState
WriteJournalState
IdempotencyState
CheckpointState
```

`ApprovalState` / `WriteJournalState`는 외부 persistence service가 아니라 per-execution mutable state container다.

## Stateless/Re-usable Services

```text
RuntimeEngine
StatementExecutor
ExpressionEvaluator
CheckEvaluator
WriteGuard
WriteIntentBuilder
IdempotencyKeyFactory
ApprovalCoordinator
CheckpointCoordinator
WriteAttemptCoordinator
PostWriteVerifier
RuntimePreflightValidator
```

외부 시스템 접근은 모두 RuntimePorts를 통해 수행한다.

---

# 3. RuntimeEngine

RuntimeEngine은 여전히 Top-Level Orchestrator다.

추가 책임:

```text
NEW / RESUME execution path coordination
suspend result handling
checkpoint restore coordination
write outcome handling
reconciliation-required result construction
```

직접 Approval UI/DB/MCP를 호출하지 않는다.

또한 RuntimeEngine은 다음을 직접 결정하지 않는다.

```text
누가 승인할 것인가
언제 Resume Job을 enqueue할 것인가
UNKNOWN_COMMIT_STATE 이후 어떤 reconciliation action을 수행할 것인가
retry를 수행할 것인가
```

Runtime은 structured state/evidence를 반환하고 Agent/Platform이 이후 Control Flow를 결정한다.

---

# 4. StatementExecutor

새 Statement:

```text
ApprovalStatement
```

처리:

```text
evaluate linked future write intent
create ApprovalRequestId
freeze WriteIntent / PayloadHash
update per-execution ApprovalState
checkpoint persist
publish ApprovalRequest
return StatementSuspended
```

중요 순서:

```text
Checkpoint durable
→ Approval Request publish
→ WAITING_FOR_APPROVAL
```

Approval Request publish는 `ApprovalRequestId` 기준으로 idempotent해야 한다.

Write 자체는 ExpressionEvaluator의 `WriteExpression` 경로가 담당한다.

---

# 5. ExpressionEvaluator

추가:

```text
WriteExpression
```

READ와 WRITE는 내부 경로를 분리한다.

```text
ReadExpression
→ ToolExecutionPort

WriteExpression
→ WriteGuard
→ IdempotencyKeyFactory
→ WriteAttemptCoordinator
→ WriteExecutionPort
```

WriteExpression은 Runtime 실행 시 `BusinessOperationId`, `PayloadHash`, `ApprovalRequestId` 등 execution-scoped identity/evidence를 사용하지만, 이러한 값은 Static IR에 저장된 compile-time semantics가 아니다.

---

# 6. WriteGuard

```python
class WriteGuard:
    def evaluate(
        self,
        request: WriteGuardRequest,
    ) -> WriteGuardDecision:
        ...
```

WriteGuard의 **runtime-current** 검사:

```text
required CHECKs all PASS
Approval Evidence valid
BusinessOperationId / ApprovalRequestId binding valid
write_intent_hash / payload_hash match
current PolicyDecision allow
write-time Business Preconditions satisfied
idempotency request ready
not replay-live
```

반면 다음은 RuntimePreflight의 책임이다.

```text
IR / feature support
Verified Package Trust Evidence
Required Tool fingerprint / contract compatibility
WRITE feature enabled
required port availability
static atomicity/idempotency capability compatibility
```

같은 검사를 Preflight와 WriteGuard에 중복 구현하지 않는다.

---

# 7. WriteIntentBuilder

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

Canonical Argument Serialization 후 다음을 계산한다.

```text
PayloadHash = HASH(canonical_write_arguments)

write_intent_hash =
HASH(
  skill_semantic_hash
  + write_node_id
  + tool_id
  + PayloadHash
)
```

`BusinessOperationId`와 `ApprovalRequestId`는 Approval/Execution instance binding에 사용되지만 Static WriteIntent semantic hash 자체를 runtime execution identity로 바꾸지는 않는다.

Approval 이후 Payload가 변경되어야 한다면 기존 Approval Evidence를 재사용하지 않고 새로운 WriteIntent / ApprovalRequest를 생성한다.

---

# 8. ApprovalCoordinator

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

책임:

```text
ApprovalRequest 구성
ApprovalRequestId 생성/보존
CheckpointCoordinator와 연계
ApprovalPort를 통한 idempotent publish
StatementSuspended 구성
```

하지 않는 일:

```text
approver selection
approval UI
notification
approval persistence ownership
approval event wait
resume job scheduling
```

이 기능은 Agent/Platform Control Plane의 책임이다.

---

# 9. CheckpointCoordinator

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

Checkpoint는 최소 다음 identity/evidence를 Resume에 필요한 수준으로 보존해야 한다.

```text
execution_id
business_operation_id
approval_id
approval_request_id
write_intent_hash
payload_hash
per-execution approval/write/idempotency state
```

Approval Request는 Checkpoint가 durable하게 저장된 후 publish되어야 한다.

---

# 10. ApprovalPort

```python
class ApprovalPort(Protocol):
    async def publish(
        self,
        request: ApprovalRequest,
    ) -> None:
        ...
```

`publish()`의 의미는 Approval Workflow를 Runtime 내부에서 실행한다는 뜻이 아니라 **Approval Request를 Control Plane에 publish**한다는 뜻이다.

Approval Event 수신과 Resume Job 생성은 NeX-AE/Agent Platform/JobQueue가 처리한다.

```text
Approval Decision Event
→ Platform Resume Job
→ Runtime ExecutionMode.RESUME
```

Runtime Worker가 Approval Event를 기다리지 않는다.

---

# 11. CheckpointPort

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

CheckpointPort는 ExecutionContext의 per-execution state를 외부에 durable하게 저장하는 persistence boundary다.

ExecutionContext 내부의 `ApprovalState` / `WriteJournalState` 자체를 persistence service로 취급하지 않는다.

---

# 12. WriteExecutionPort

READ와 WRITE를 분리하는 것을 권장한다.

```python
class WriteExecutionPort(Protocol):
    async def execute(
        self,
        request: WriteCallRequest,
    ) -> WriteExecutionOutcome:
        ...
```

`WriteCallRequest`는 Runtime에서 확정한 다음 identity/evidence를 포함해야 한다.

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
```

기존 ToolExecutionPort를 Unified Union으로 확장할 수도 있으나, v0.2에서는 Side Effect 경계를 코드 수준에서 명확히 분리하는 편을 권장한다.

---

# 13. IdempotencyKeyFactory

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

Pure deterministic service다.

중요 분리:

```text
IdempotencyKey
= stable operation identity

PayloadHash
= canonical request payload identity
```

따라서 `PayloadHash`를 IdempotencyKey 생성 input에 넣어 서로 다른 payload가 서로 다른 key가 되어 conflict detection을 우회하게 해서는 안 된다.

동일 `TenantId + BusinessOperationId + WriteNodeId`는 Suspend/Resume/Re-execution/Reconciliation에서 동일 key를 재사용해야 한다.

---

# 14. WriteCallRequest

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

business_precondition_evidence
call_context
```

`BusinessOperationId ≠ execution_id ≠ invocation_id`를 유지한다.

또한:

```text
IdempotencyKey ≠ PayloadHash
```

를 타입/필드 수준에서 분리한다.

---

# 15. WriteExecutionOutcome

Canonical 3-way Commit Algebra:

```text
WriteCommitted
WriteNotCommitted
WriteCommitUnknown
```

일반 `WriteFailure`를 별도의 네 번째 commit state처럼 두지 않는다.

Tool/Provider error라도 commit 여부가 확실히 `NOT_COMMITTED`이면 `WriteNotCommitted(error=...)`로 표현하고, provider 호출 이후 commit 여부를 알 수 없으면 `WriteCommitUnknown`으로 표현한다.

Commit uncertainty를 정상 Failure에 숨기지 않는다.

---

# 16. PostWriteVerifier

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

Verification은 READ Port를 사용할 수 있다.

Typed status:

```text
NOT_REQUESTED
VERIFIED
FAILED
UNKNOWN
```

Verification 실패/불확실을 Commit 실패로 재분류하지 않는다.

```text
CommitState = COMMITTED
VerificationStatus = FAILED/UNKNOWN
```

이어도 자동으로 동일 WRITE를 다시 실행해서는 안 된다.

---

# 17. Reconciliation

`WriteCommitUnknown` 발생 시:

```text
RuntimeEngine
→ WriteJournalState append
→ CommitState = UNKNOWN_COMMIT_STATE
→ ExecutionStatus / Disposition = RECONCILIATION_REQUIRED
→ structured evidence Result
```

Runtime이 자동으로 새 WRITE를 발생시키지 않는다.

Runtime은 다음 evidence를 반환할 수 있다.

```text
business_operation_id
idempotency_key
payload_hash
tool_id
provider_transaction_id
business_reference(optional)
verification_hint
timeout / transport evidence
```

어떤 reconciliation action을 선택할지, 언제 수행할지는 Agent/Platform Control Plane이 결정한다.

---

# 18. RuntimePreflightValidator v0.2

RuntimePreflight의 책임:

```text
IR 1.0 / 1.1 support
language/feature compatibility
Verified Package / Verified Skill Trust Evidence
WRITE feature enabled
RequiredTool fingerprint / contract hash match
Tool Capability WRITE
atomicity capability
idempotency capability
required port availability
```

RuntimePreflight가 소유하지 않는 현재 실행 판단:

```text
Approval Evidence validity
current Tenant/User PolicyDecision
write-time Business Preconditions
runtime PayloadHash binding
IdempotencyKey request state
```

이 항목들은 WriteGuard/Runtime current-state validation에서 처리한다.

Production WRITE는 raw `SkillObject`에 대한 별도 독립 signature verification path를 새로 만들지 않고 Signed NSP에서 생성된 Trust Evidence를 소비한다.

---

# 19. RuntimePorts v0.2

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

    # Durable WRITE_REQUESTED / outcome evidence boundary.
    write_evidence: WriteEvidencePort

    trace: TraceSink
    provenance: ProvenanceStore
    clock: RuntimeClock
    cancellation: CancellationToken

    policy: RuntimePolicyPort
```

Production WRITE의 Package Signature/Trust 검증은 RuntimePorts의 raw `SignatureVerifier(skill)`로 중복 수행하지 않고, Runtime이 받은 `VerifiedSkillArtifact` 또는 `PackageTrustEvidence`를 RuntimePreflight가 확인하는 방향을 권장한다.

실제 Repository에서 기존 v0.1 trust adapter seam을 재사용할 수 있으며, 새 physical module tree를 만들기 위해 big-bang refactor하지 않는다.

---

# 20. Runtime Policy Port

```python
class RuntimePolicyPort(Protocol):
    def authorize_write(
        self,
        request: WritePolicyRequest,
    ) -> PolicyDecision:
        ...
```

Tenant/User entitlement와 Risk Policy를 Runtime Core에 하드코딩하지 않는다.

`RiskLevel`은 static classification metadata이고 `PolicyDecision`은 현재 execution context에 대한 external decision이다.

Approval 대기 중 정책이 변경될 수 있으므로 WRITE 직전에 현재 PolicyDecision을 다시 확인할 수 있어야 한다.

Policy authoring 자체는 NSL Runtime의 책임이 아니다.

---

# 21. Verified Package Trust Evidence

v0.2 Closure에서는 raw `SkillObject`를 Runtime 내부에서 별도 서명 검증하는 새로운 `SignatureVerifier` 경로를 canonical model로 두지 않는다.

대신 기존 v0.1 Signed NSP Trust Boundary를 재사용한다.

```text
Signed NSP
   ↓
Package / Publisher Signature Verification
   ↓
Verified Package / Verified Skill Artifact
   ↓
PackageTrustEvidence
   ↓
RuntimePreflight
```

권장 shared/runtime-facing model:

```python
@dataclass(frozen=True)
class PackageTrustEvidence:
    package_id: str
    package_hash: str
    publisher_id: str
    signing_key_id: str
    verified_at: datetime
    trust_status: TrustStatus
```

구체적인 verifier implementation은 NSP Package/Security Adapter의 책임이다.

---

# 22. ExecutionResult v0.2

v0.1 Result Contract를 유지하면서 다음 필드를 additive하게 추가한다.

```text
pre_write_eligibility
approval
write
verification
suspension
```

Public field name은 Runtime Python Interface의 canonical `ExecutionResult`와 동일하며, `approval`/`write`/`verification`은 각각 Summary DTO를 담는다.

다음은 정상 구조화된 Result가 될 수 있다.

```text
WAITING_FOR_APPROVAL
RECONCILIATION_REQUIRED
```

READ-only IR 1.0 실행에서는 Approval/Write/Verification/Suspension 필드가 `None` 또는 Not Applicable일 수 있다.

`RESUME_QUEUED`는 Runtime Result status가 아니라 Platform Queue State다.

---

# 23. Replay

`ReplayWriteExecutor`가 WriteExecutionPort를 구현한다.

실제 Provider 호출을 하지 않는다.

v0.2 Replay는 WRITE Outcome뿐 아니라 실행 결과에 영향을 주는 Control Evidence도 Snapshot으로 재사용한다.

```text
Approval Evidence Snapshot
Policy Decision Snapshot
Package Trust / Preflight Evidence
Write Outcome Snapshot
Verification Outcome Snapshot
```

Replay 중 현재 Approval/Policy/Trust 서비스를 live 호출하여 과거 execution semantics를 바꾸지 않는다.

> Replay = no live control-plane decision calls + no live WRITE

---

# 24. Mock

```text
MockApprovalPort
MemoryCheckpointPort
MockWriteExecutor
ReplayWriteExecutor
FakeRuntimePolicyPort
FakeClock
FakePackageTrustEvidence
```

v0.2 Unit Test의 핵심 Test Double이다.

개별 Runtime `FakeSignatureVerifier`보다 Verified Package Trust Evidence 입력을 모킹하는 편을 canonical path로 사용한다.

---

# 25. Module 구조

다음은 logical responsibility example이다.

```text
runtime/
├─ engine.py
├─ request.py
├─ result.py
├─ preflight.py
├─ context.py
├─ frame.py
├─ statements.py
├─ expressions.py
├─ approvals.py
├─ writes.py
├─ write_guard.py
├─ idempotency.py
├─ checkpoints.py
├─ verification.py
├─ resources.py
├─ ports.py
└─ cancellation.py
```

이 구조는 실제 Repository를 해당 디렉터리 구조로 강제 재배치하라는 의미가 아니다.

```text
Repository-first refactor
→ 기존 v0.1 물리 구조 확인
→ 책임 혼합 hotspot만 우선 분리
→ logical responsibility를 유지하되 unnecessary package churn 금지
```

문서 구조를 맞추기 위한 big-bang module reorganization은 하지 않는다.

---

# 26. Dependency Rule

기존 원칙 유지:

```text
runtime → core
runtime → ir
runtime → tools protocols
runtime → validation
runtime → audit protocols

runtime !→ compiler
tools !→ runtime
```

추가 Closure boundary:

```text
runtime core !→ Approval UI / Job Queue implementation
runtime core !→ Policy authoring implementation
runtime core !→ NSP package signer/verifier implementation
runtime core !→ Reconciliation orchestrator
```

Ports/Evidence를 통해 외부 기능을 소비하되 ownership을 Runtime으로 이동하지 않는다.

---

# 27. Object Lifetime

Application / Reusable:

```text
RuntimeEngine
WriteGuard
IdempotencyKeyFactory
PostWriteVerifier
RuntimePreflightValidator
```

Execution:

```text
ExecutionContext
ApprovalState
WriteJournalState
IdempotencyState
```

Suspend Persisted:

```text
ExecutionCheckpoint
```

Approval Instance:

```text
ApprovalRequest
ApprovalEvidence
ApprovalRequestId
```

Write Call:

```text
WriteCallRequest
WriteExecutionOutcome
WriteAttemptRecord
```

Control Plane / Package Trust Evidence는 ExecutionContext 내부 service로 보관하지 않고 immutable input/evidence 또는 Port를 통해 전달한다.

---

# 28. 최종 관계

```text
RuntimeEngine
  │
  ├─ RuntimePreflightValidator
  │      └─ Verified Package Trust Evidence
  │
  ├─ StatementExecutor
  │    └─ ApprovalCoordinator
  │          └─ CheckpointCoordinator
  │
  ├─ ExpressionEvaluator
  │    ├─ READ Port
  │    └─ WriteGuard
  │          ├─ Current PolicyDecision
  │          ├─ ApprovalEvidence
  │          ├─ Business Preconditions
  │          └─ IdempotencyKeyFactory
  │                    │
  │                    ▼
  │            WriteAttemptCoordinator
  │              ├─ durable WRITE_REQUESTED
  │              └─ WriteExecutionPort
  │
  └─ PostWriteVerifier
```

WRITE Provider 호출 전에는 최소 다음 evidence를 durable하게 남겨야 한다.

```text
BusinessOperationId
IdempotencyKey
PayloadHash
ToolInvocationId
WRITE_REQUESTED
```

Provider 호출 이후 Cancellation/Timeout이 발생하고 Commit 여부를 알 수 없으면 이를 단순 `CANCELLED` 또는 `NOT_COMMITTED`로 축소하지 않고 `UNKNOWN_COMMIT_STATE → RECONCILIATION_REQUIRED`로 처리한다.

---

# 28.1 Durable Write Attempt / Cancellation Safety

`WriteAttemptCoordinator`는 실제 Provider WRITE 호출 직전의 crash-consistency 경계를 관리한다.

권장 흐름:

```text
WriteGuard PASS
  ↓
IdempotencyKey 확정
  ↓
PayloadHash 확정
  ↓
ToolInvocationId 생성
  ↓
WRITE_REQUESTED durable persist
  ↓
WriteExecutionPort.execute()
  ↓
WriteExecutionOutcome persist
```

복구 시:

```text
WRITE_REQUESTED 존재
+ terminal WriteOutcome 없음
→ blind re-invocation 금지
→ reconciliation / idempotency query path
```

Cancellation / Timeout 규칙:

```text
Provider 미호출이 확실
→ CANCELLED / NOT_COMMITTED 가능

Provider 호출 이후 Commit 여부 불명
→ UNKNOWN_COMMIT_STATE
→ RECONCILIATION_REQUIRED
```

---

# 28.2 Retry Safety Boundary

Runtime은 actual retry policy를 소유하지 않는다.

Runtime/Tool Contract는 다음과 같은 `RetrySafety` evidence를 제공할 수 있다.

```text
SAFE_TO_RETRY
UNSAFE_TO_RETRY
REQUIRES_RECONCILIATION
```

실제 Retry 여부와 시점은 Agent/Platform Control Plane이 결정한다.

---

# 28.3 Closure Alignment Trace

본 문서에 적용한 주요 Unified Change Ledger 항목:

```text
CHG-003  BusinessOperationId 도입
CHG-004  IdempotencyKey / PayloadHash 분리
CHG-005  ApprovalRequestId + Evidence Binding
CHG-006  Approval Workflow Ownership → Agent/Platform
CHG-008  Runtime Status Boundary 정리
CHG-010  Signed NSP Trust Boundary 재사용
CHG-017  Write-time Business Preconditions
CHG-019  Provider 호출 전 durable WRITE_REQUESTED
CHG-020  Cancellation/Timeout Commit Uncertainty
CHG-021  RuntimePreflight / WriteGuard 책임 분리
CHG-022  WriteOutcome 3-way Canonical Algebra
CHG-023  Risk Classification / PolicyDecision 분리
CHG-025  Replay Control-evidence Snapshot
CHG-026  RetrySafety evidence / actual retry decision 분리
CHG-027  ExecutionContext state-only terminology
CHG-029  VerificationStatus typed + Commit 분리
CHG-032  Physical module refactor = repository-first
```

본 문서는 위 결정을 Runtime Class/Object 책임과 lifetime/port 경계로 구체화한다.

---

# 29. 최종 정의

> **v0.2 Runtime은 Side Effect를 일반 Expression 하나로 취급하지 않고, Verified Trust / Approval / Checkpoint / WriteGuard / BusinessOperation-based Idempotency / Durable Write Attempt / Commit / Verification이라는 명시적인 객체 경계를 통해 Controlled Write를 실행한다. Approval Workflow, Retry, Reconciliation orchestration은 Agent/Platform Control Plane에 남긴다.**
