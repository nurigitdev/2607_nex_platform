# NeX Skill Runtime ExecutionContext Detailed Design v0.2

**문서 버전:** v0.2 — Closure Aligned  
**작성일:** 2026-08-23  
**대상:** NSL Runtime v0.2 / IR 1.1  
**Architecture Closure 기준:** `NSL v0.2 Architecture Consistency Closure and Unified Change Ledger v1.0 — FROZEN`

---

# 1. 목적

v0.1 ExecutionContext의 Value/Type/Completeness/Provenance/Check/Emit/Resource 구조를 유지하면서 Approval 대기, Resume, Controlled WRITE Idempotency, Commit/Verification Evidence와 Side-Effect Journal State를 추가한다.

v0.2 ExecutionContext의 핵심 원칙:

```text
ExecutionContext
= per-execution mutable state

ExecutionContext
!= external service container
!= approval workflow engine
!= policy engine
!= persistence repository
```

또한 동일 Business WRITE가 Suspend/Resume/Re-execution/Reconciliation을 거쳐도 같은 의미를 유지하도록 `BusinessOperationId`를 실행 identity에 포함한다.

v0.2에서도 v0.1의 Principal / DataPolicy Security Context를 제거하지 않는다.

---

# 2. Top-Level Object Model

```text
ExecutionContext
├─ identity
│   ├─ execution_id
│   └─ business_operation_id        # v0.2
├─ security_context
│   ├─ principal                    # v0.1 preserved
│   └─ data_policy                  # v0.1 preserved
├─ inputs
├─ contexts
├─ FrameStack
├─ CheckStore
├─ EmitBuffer
├─ ResourceMeter
│
├─ ApprovalStore                    # per-execution state
├─ WriteJournal                     # per-execution append-only state
├─ IdempotencyState                 # v0.2
├─ ControlEvidenceState             # approval/policy/trust snapshots
├─ CheckpointState                  # v0.2
│
└─ ExecutionStatus
```

`ApprovalStore`와 `WriteJournal`이라는 이름은 외부 Persistence Service를 의미하지 않는다. 둘 다 **ExecutionContext 내부의 per-execution state container**다.

External Service / Repository / Port는 Context에 넣지 않는다.

---

# 3. 기존 ValueEnvelope 유지

```python
@dataclass(frozen=True, slots=True)
class ValueEnvelope:
    value: object
    type_info: TypeInfo
    presence: Presence
    completeness: Completeness
    provenance_ref: ProvenanceRef
```

v0.2 Controlled Write 추가로 인해 `ValueEnvelope`, `Presence`, `Completeness`, Provenance 의미론을 변경하지 않는다.

WRITE가 `NOT_COMMITTED` 또는 `UNKNOWN_COMMIT_STATE`인 경우 정상 Business Value로 위장한 `ValueEnvelope`을 생성하지 않는다.

---

# 4. ExecutionStatus v0.2

v0.1 Runtime 상태를 additive하게 보존한다.

```text
CREATED
RUNNING

WAITING_FOR_APPROVAL          # v0.2
RECONCILIATION_REQUIRED      # v0.2

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
→ Agent / Platform Queue State

WRITE_IN_PROGRESS
→ internal write-attempt state / WriteJournal event
```

Approval REJECT는 Runtime Technical Failure가 아닌 Business Outcome으로 `COMPLETED` 처리할 수 있다.

`UNKNOWN_COMMIT_STATE`는 Commit Outcome이며, Runtime의 최종 disposition/status는 `RECONCILIATION_REQUIRED`로 전환할 수 있다.

---

# 5. ApprovalRecord

정적 Source/IR ID와 실행 instance ID를 분리한다.

```python
@dataclass(frozen=True)
class ApprovalRecord:
    approval_id: str                      # static Source/IR Approval ID
    approval_request_id: ApprovalRequestId  # runtime instance ID
    business_operation_id: BusinessOperationId

    node_id: NodeId
    status: ApprovalStatus
    message: str

    payload_hash: PayloadHash
    write_intent_hash: str

    requested_at: datetime
    expires_at: datetime | None

    approver_id: str | None
    decided_at: datetime | None

    protected_payload_ref: str | None
    data_classification: DataClassification | None
```

중요:

```text
ApprovalId
!= ApprovalRequestId
```

Approval Evidence는 최소한 `BusinessOperationId`, `ApprovalRequestId`, `skill semantic hash`, `write_intent_hash`, `payload_hash`와 검증 가능하게 Binding되어야 한다.

---

# 6. ApprovalStore

```python
class ApprovalStore:
    def put(self, record: ApprovalRecord) -> None:
        ...

    def get(self, approval_request_id: ApprovalRequestId) -> ApprovalRecord:
        ...

    def items(self) -> tuple[ApprovalRecord, ...]:
        ...
```

`ApprovalStore`는 ExecutionContext 내부의 **Per-Execution Mutable State Container**다.

```text
ApprovalStore
!= Approval DB
!= Approval Service
!= Approval Workflow
```

Persistent 저장은 `CheckpointPort`가 담당하며, Approval Routing/UI/Notification/Persistence lifecycle과 Resume Job Scheduling은 Agent/Platform Control Plane이 담당한다.

---

# 7. WriteIntent

```python
@dataclass(frozen=True)
class WriteIntent:
    node_id: NodeId
    tool_ref: ToolRef

    canonical_arguments: Mapping[str, ValueEnvelope]
    payload_hash: PayloadHash
    write_intent_hash: str

    approval_id: str
    business_operation_id: BusinessOperationId
```

`WriteIntent`는 Approval Request 생성 전에 Canonical Payload 의미를 Freeze한다. `ApprovalRequestId`는 Freeze된 WriteIntent를 기반으로 Approval Request를 만들 때 생성하며, WriteIntent 자체에는 포함하지 않는다.

권장 identity 관계:

```text
canonical_arguments
      ↓
PayloadHash

skill_semantic_hash
+ write_node_id
+ tool_id
+ PayloadHash
      ↓
write_intent_hash
```

Payload를 변경해야 하면 기존 Approval을 재사용하지 않고 새로운 WriteIntent / ApprovalRequest를 생성한다.

---

# 8. WriteJournalEntry

WRITE Provider 호출 **전/후**의 durable evidence를 모두 표현할 수 있어야 한다.

```python
class WriteJournalEventType(str, Enum):
    WRITE_REQUESTED = "WRITE_REQUESTED"
    WRITE_COMMITTED = "WRITE_COMMITTED"
    WRITE_NOT_COMMITTED = "WRITE_NOT_COMMITTED"
    WRITE_COMMIT_UNKNOWN = "WRITE_COMMIT_UNKNOWN"
    WRITE_VERIFIED = "WRITE_VERIFIED"
    WRITE_VERIFICATION_FAILED = "WRITE_VERIFICATION_FAILED"


@dataclass(frozen=True)
class WriteJournalEntry:
    event_type: WriteJournalEventType

    business_operation_id: BusinessOperationId
    node_id: NodeId
    tool_id: ToolId
    invocation_id: ToolInvocationId

    idempotency_key: IdempotencyKey
    payload_hash: PayloadHash
    write_intent_hash: str
    approval_request_id: ApprovalRequestId

    commit_state: CommitState | None
    business_reference: str | None
    provider_transaction_id: str | None
    verification_status: VerificationStatus | None

    recorded_at: datetime
```

`WRITE_REQUESTED`는 Provider 호출 전에 durable하게 기록되어야 하므로 `commit_state=None`일 수 있다.

`verification_status`는 raw string이 아니라 shared typed `VerificationStatus`를 사용한다.

---

# 9. WriteJournal

```python
class WriteJournal:
    def append(self, entry: WriteJournalEntry) -> None:
        ...

    def latest_for(
        self,
        business_operation_id: BusinessOperationId,
        node_id: NodeId,
    ) -> WriteJournalEntry | None:
        ...

    def entries_for(
        self,
        business_operation_id: BusinessOperationId,
        node_id: NodeId,
    ) -> tuple[WriteJournalEntry, ...]:
        ...
```

Append-only를 기본으로 한다.

Recovery 핵심 규칙:

```text
WRITE_REQUESTED 존재
+
Terminal Commit Outcome 없음
→ 동일 WRITE를 새 Key로 재호출하지 않음
→ provider/idempotency evidence 확인
→ RECONCILIATION_REQUIRED 가능
```

`WriteJournal`은 Runtime state이고 외부 durable persistence 자체는 `CheckpointPort` 또는 Runtime persistence adapter가 담당한다.

---

# 10. IdempotencyState

```python
@dataclass
class IdempotencyState:
    keys_by_write_node: dict[NodeId, IdempotencyKey]
    payload_hashes_by_write_node: dict[NodeId, PayloadHash]
```

Key 생성 기준은 `execution_id`가 아니라 stable `BusinessOperationId`다.

```text
IdempotencyKey =
HASH(
    tenant_id
    + business_operation_id
    + write_node_id
)

PayloadHash =
HASH(canonical_write_arguments)
```

Suspend/Resume에서는 동일 Key를 재사용한다.

새 Runtime execution이더라도 동일 `TenantId + BusinessOperationId + WriteNodeId`의 동일 Business WRITE를 재개하는 경우 동일 Idempotency Domain을 유지해야 한다.

동일 `IdempotencyKey` + 다른 `PayloadHash`는 conflict로 처리한다.

---

# 11. CheckpointState

```python
@dataclass
class CheckpointState:
    checkpoint_version: int
    last_completed_node_id: NodeId | None
    suspended_at_node_id: NodeId | None
    trace_sequence: int

    approval_request_published: bool = False
    write_request_durable: bool = False
```

`approval_request_published`는 Checkpoint와 Approval Request publish 간 crash recovery에 사용할 수 있다.

`write_request_durable`은 Provider 호출 전에 `WRITE_REQUESTED` evidence가 Checkpoint/Persistence에 반영되었는지 확인하는 execution-local guard다.

실제 durable persistence 여부 판단은 `CheckpointPort`/Runtime persistence adapter의 성공 결과를 기준으로 한다.

---

# 12. Execution Checkpoint Snapshot

Persistence용 Immutable DTO:

```python
@dataclass(frozen=True)
class ExecutionCheckpoint:
    execution_id: ExecutionId
    business_operation_id: BusinessOperationId

    skill_id: SkillId
    skill_version: str
    semantic_hash: str
    ir_version: str
    runtime_version: str

    principal_snapshot: ...
    data_policy_snapshot: ...

    inputs: ...
    contexts: ...
    frame_snapshot: ...
    checks: ...

    approvals: ...
    write_journal: ...
    idempotency_state: ...

    control_evidence: ...
    resources: ...
    checkpoint_state: ...
```

`control_evidence`에는 실행 재현/Resume 검증에 필요한 범위에서 다음 Snapshot/Reference가 포함될 수 있다.

```text
Approval Evidence
Policy Decision / Policy Evidence
Verified Package Trust Evidence
Tool Snapshot
Verification Evidence
```

민감 WRITE Payload 전체를 generic checkpoint metadata로 중복 복제하지 않고 Protected Snapshot/Reference를 사용할 수 있어야 한다.

---

# 13. Approval Suspend Flow

Approval Request publish보다 Checkpoint durability가 먼저 보장되어야 한다.

```text
StatementExecutor
 ↓
ApprovalStatement
 ↓
WriteIntent Freeze
 ↓
ApprovalRequestId 생성
 ↓
ApprovalStore=PENDING
 ↓
Checkpoint Persist (durable)
 ↓
ApprovalPort.request() / Approval Request Publish (idempotent)
 ↓
ExecutionStatus=WAITING_FOR_APPROVAL
 ↓
SuspendExecution signal / Worker exit
```

Crash recovery 원칙:

```text
Checkpoint saved
+ Approval Request not yet published
→ same ApprovalRequestId로 publish 가능

Approval Request published
+ Worker crash
→ persisted checkpoint로 Resume 가능
```

Approval Request 전달 이후 승인자 Routing/UI/Notification/Persistence와 Resume Job Scheduling은 Agent/Platform 책임이다.

---

# 14. Resume Flow

```text
ExecutionCheckpoint Load
 ↓
checkpoint integrity verify
 ↓
semantic hash / IR version verify
 ↓
Verified Signed NSP / Package Trust Evidence preflight
 ↓
Principal / DataPolicy restore + current authorization checks as required
 ↓
ExecutionContext restore
 ↓
Approval Evidence apply
 ↓
BusinessOperationId / ApprovalRequestId binding verify
 ↓
payload_hash / write_intent_hash verify
 ↓
current PolicyDecision verify
 ↓
write-time Business Preconditions verify
 ↓
resume after approval node
```

`RESUME_QUEUED`는 이 흐름의 Runtime 상태가 아니라 Agent/Platform Queue 상태다.

Resume 과정에서 Payload가 승인 당시와 달라졌다면 WRITE로 진행하지 않고 새로운 Approval이 필요하다.

---

# 15. ResourceMeter와 Suspend

Approval 대기시간은 Skill Execution CPU/Active Runtime Duration Limit에 포함하지 않는 것을 권장한다.

대신:

```text
active_runtime_duration
approval_wait_duration
```

을 분리한다.

Approval TTL은 별도 정책이다.

단, Approval TTL은 External Business State freshness를 보장하지 않는다. 실제 WRITE 직전 Business Preconditions를 별도로 재검증해야 한다.

---

# 16. Tool Snapshot

Approval 이전 READ 결과는 Checkpoint에 Snapshot/Reference를 보관한다.

Resume 후 모든 READ를 자동 재실행하면 Approval된 Payload가 달라질 수 있으므로 v0.2 Strict에서는 승인에 사용된 Write Intent를 Freeze하는 것을 우선한다.

다음 원칙을 지킨다.

```text
승인된 Payload 유지
→ 기존 Approval Evidence 사용 가능

Payload 재계산 결과 변경
→ 기존 Approval 무효
→ 새 WriteIntent / 새 ApprovalRequest 필요
```

Replay/Resume에 필요한 Tool Snapshot은 raw payload 복제와 구분하여 provenance/evidence reference 형태로 보존할 수 있다.

---

# 17. Freshness

장시간 Approval 후 External State가 변할 수 있다.

`approval_ttl`은 Approval Evidence 자체의 유효기간을 통제할 수 있지만 TOCTOU 문제를 완전히 해결하지 못한다.

v0.2에서는 WRITE 직전 다음 중 하나 이상의 Business Precondition 검증을 요구한다.

```text
version / revision
ETag / precondition token
transactional business rule revalidation
equivalent provider-side precondition
```

예:

```text
Approval 당시 PERIOD_OPEN = true
        .
        . approval wait
        .
WRITE 직전 PERIOD_OPEN = false
→ WRITE 금지
```

Canonical Business API는 실제 atomic transaction과 같은 경계에서 가능한 한 Business Preconditions를 재검증해야 한다.

---

# 18. Write Result → Context

`COMMITTED` 후에만 정상 Business Result를 Context에 Binding한다.

```text
WriteCommitted
 ↓
WriteResultEnvelope
 ↓
Provenance record
 ↓
ValueEnvelope
 ↓
LET symbol binding
```

다음에서는 정상 Result Binding을 생성하지 않는다.

```text
WriteNotCommitted
WriteCommitUnknown
```

`VerificationStatus`는 CommitState와 별도다.

```text
CommitState = COMMITTED
VerificationStatus = FAILED
```

라고 해서 Commit을 되돌리거나 결과를 `NOT_COMMITTED`로 재분류하지 않는다.

---

# 19. UNKNOWN Commit

```text
WriteJournal append:
  WRITE_COMMIT_UNKNOWN
  CommitState = UNKNOWN_COMMIT_STATE

ExecutionStatus
  = RECONCILIATION_REQUIRED
```

Frame에 성공 Result를 Binding하지 않는다.

NSL Runtime은 자동으로 새 WRITE를 발생시키지 않는다.

다음 경우도 Commit uncertainty를 보존해야 한다.

```text
Provider 호출 이후 timeout
Provider 호출 이후 cancellation
Transport 단절로 provider commit 여부 불명
Process crash 후 WRITE_REQUESTED만 존재
```

Provider 호출 전임이 확실하면 `CANCELLED` / `NOT_COMMITTED` 처리가 가능하지만, Provider 호출 이후 commit 여부가 불확실하면 `UNKNOWN_COMMIT_STATE`로 축소 없이 보존한다.

Reconciliation action 선택과 Retry 여부는 Agent/Platform Control Plane이 결정한다.

---

# 20. Audit / Trace

Context 자체가 `TraceSink` Service를 보유하지 않는 원칙을 유지한다.

`RuntimePorts.trace`를 통해 Event를 기록한다.

Context에는 trace sequence와 per-execution audit evidence state만 둘 수 있다.

권장 WRITE 관련 event:

```text
WRITE_INTENT_CREATED
APPROVAL_REQUESTED
EXECUTION_SUSPENDED
EXECUTION_RESUMED
WRITE_REQUESTED
WRITE_COMMIT_CONFIRMED
WRITE_COMMIT_UNKNOWN
WRITE_VERIFIED
WRITE_VERIFICATION_FAILED
```

가능한 경우 다음 identity를 연결한다.

```text
execution_id
business_operation_id
approval_request_id
node_id
invocation_id
idempotency_key
payload_hash
write_intent_hash
```

Generic trace/audit event에 raw sensitive payload를 기본 복제하지 않는다.

---

# 21. Determinism

같은 다음 Evidence Set이면 같은 Replay Result를 생성할 수 있어야 한다.

```text
IR
Input
Runtime Context
Principal / DataPolicy Snapshot

Tool Snapshots
Approval Evidence Snapshot
Policy Decision Snapshot
Verified Package Trust Evidence
Write Outcome Snapshot
Verification Outcome Snapshot
```

Replay에서는:

```text
새 BusinessOperationId 임의 생성 금지
새 IdempotencyKey 생성 금지
Live Approval Decision 호출 금지
Live Policy Decision 호출 금지
Live Trust Decision 호출 금지
Live WRITE 호출 금지
```

즉:

> **Replay = no live control-plane decision calls + no live WRITE**

Replay Adapter는 recorded evidence/snapshot을 같은 Runtime execution path에 공급한다.

---

# 22. ExecutionContext Python Model

```python
@dataclass
class ExecutionContext:
    execution_id: ExecutionId
    business_operation_id: BusinessOperationId

    skill_id: SkillId
    skill_version: str
    nso_semantic_hash: str
    runtime_version: str

    principal: ExecutionPrincipal
    data_policy: DataPolicy

    inputs: Mapping[SymbolId, ValueEnvelope]
    contexts: Mapping[SymbolId, ValueEnvelope]

    frames: FrameStack
    checks: CheckStore
    emits: EmitBuffer
    resources: ResourceMeter

    approvals: ApprovalStore
    writes: WriteJournal
    idempotency: IdempotencyState
    control_evidence: ControlEvidenceState
    checkpoint: CheckpointState

    status: ExecutionStatus
```

설계 의도:

```text
ExecutionContext
= state only

RuntimePorts
= external capabilities / services
```

`BusinessOperationId`는 Runtime invocation에서 전달받는 stable business identity이며 Compiler/IR이 생성하지 않는다.

---

# 23. Context에 넣지 않는 것

```text
ToolExecutor
WriteExecutionPort
ApprovalPort
CheckpointRepository / CheckpointPort
TraceSink
ProvenanceStore
Database
MCP Client
Package Signature Verifier
Policy Service
Resume Queue
Reconciliation Orchestrator
```

모두 External Port / Service / Platform Responsibility다.

특히 `ControlEvidenceState`에는 **검증 결과 또는 Snapshot/Reference**만 둘 수 있고, Policy Engine이나 Trust Verifier 객체 자체를 보유해서는 안 된다.

---

# 24. Checkpoint Security

Checkpoint에는 민감한 업무 데이터와 WRITE/Approval evidence가 포함될 수 있다.

요구:

```text
tenant isolation
encryption at rest
integrity hash
access control
retention
redaction policy
classification-aware handling
```

Approval/Event/Audit에는 raw Payload를 기본 복제하지 않는다.

권장 모델:

```text
display_safe_summary
protected_payload_ref
payload_hash
data_classification
```

Resume 시 Protected Snapshot을 조회할 경우 Principal / Tenant / DataPolicy 권한을 다시 적용할 수 있어야 한다.

---

# 25. Backward Compatibility

IR 1.0 실행에서는 Approval/Write/Idempotency/ControlEvidence State가 비어 있거나 Not Applicable 상태로 생성된다.

v0.1 Runtime behavior와 다음 계약을 보존한다.

```text
ValueEnvelope / Presence / Completeness
Check / Emit / Resource semantics
Principal / DataPolicy security context
VALIDATION_ERROR 등 v0.1 ExecutionStatus
IR 1.0 deterministic replay behavior
```

v0.2 state 추가는 additive extension이어야 하며 READ-only consumer가 WRITE 관련 state를 강제로 해석하도록 만들지 않는다.

---

# 25.1 Closure Alignment Trace

본 문서에 적용한 주요 Unified Change Ledger 항목:

```text
CHG-003  BusinessOperationId 도입
CHG-004  IdempotencyKey / PayloadHash 분리
CHG-005  ApprovalRequestId + Evidence Binding
CHG-006  Approval Workflow Ownership → Agent/Platform
CHG-008  ExecutionStatus 정리
CHG-009  Principal / DataPolicy Request Contract 보존
CHG-010  Signed NSP Trust Evidence 재사용
CHG-017  TOCTOU / Write-time Business Preconditions
CHG-018  Checkpoint → Approval Publish Crash Consistency
CHG-019  Provider 호출 전 durable WRITE_REQUESTED
CHG-020  Cancellation/Timeout Commit Uncertainty
CHG-024  Approval Payload Protected-reference Model
CHG-025  Replay Control-Evidence Snapshot
CHG-027  ExecutionContext State-only Terminology
CHG-029  VerificationStatus typed + Commit 분리
```

본 문서는 위 Closure 결정을 **per-execution mutable state / checkpoint / recovery model** 관점에서 구체화한다.

---

# 26. 최종 정의

> **v0.2 ExecutionContext는 외부 Service Container가 아니라 Side-Effect-Aware per-execution state다. BusinessOperationId, Approval Evidence, Idempotency/Payload Identity, durable WRITE attempt evidence, Commit/Verification state를 보존하여 Suspend/Resume/Crash Recovery 이후에도 동일 업무 WRITE의 의미와 안전성을 유지한다.**
