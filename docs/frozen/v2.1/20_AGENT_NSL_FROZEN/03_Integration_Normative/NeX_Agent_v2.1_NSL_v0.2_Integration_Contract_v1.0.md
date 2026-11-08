# NeX Agent v2.1 ↔ NSL v0.2 Integration Contract v1.0

**상태:** NORMATIVE DRAFT — CONTROLLED AMENDMENT BASELINE  
**적용 범위:** AE-API / Unified Agent Runtime / NeX Agent / NSL v0.2 Integration  
**NSL 기준:** NSL v0.2 Frozen — 변경 없음

# 1. Responsibility Boundary

```text
Agent / Platform
= Agent lifecycle, Planning/Compile, OA outer admission, EA Operation Trust,
  Human workflow orchestration, Wait/Resume scheduling,
  BusinessOperationId stability, Reconciliation decision, Agent Result

NSL
= deterministic Skill execution, WriteIntent, NSL Approval binding,
  actual WRITE IdempotencyKey, CommitState, VerificationStatus,
  detailed execution/write evidence

Integration Layer
= invocation adaptation, exact artifact resolution,
  identity/context mapping, suspension bridge,
  cross-layer control conformance, result/evidence projection
```

# 2. SkillExecutionRequest v1

Agent `ExecutionContext v1`이라는 이름을 사용하지 않는다.

```text
SkillExecutionRequest
├─ agent_execution_id
├─ executable_plan_id
├─ executable_step_id
├─ nsl_execution_id
├─ business_operation_id
├─ tenant_id
├─ skill_id
├─ exact_skill_version
├─ runtime_contract_ref
├─ compiled_inputs
├─ explicit_resource_refs
├─ executing_principal
├─ business_actor / on_behalf_of
├─ effective_role_bindings
├─ org_scope
├─ project_scope
├─ data_classification
├─ correlation_id
├─ causation_id
├─ agent_context_ref/hash
├─ mode = NEW | RESUME
└─ resume payload
```

# 3. Identity Contract

```text
AgentExecutionId 1:N NSLExecutionId

NSLExecutionId
= one logical NSL execution lifecycle; NEW → WAIT → RESUME 동안 stable

BusinessOperationId
= Agent/Platform-owned stable semantic operation identity
= retry/resume/reconciliation 동안 stable

TenantId
!= OrgScope
!= ProjectScope
```

모든 NSL invocation에 `BusinessOperationId`를 공급한다. READ에서는 correlation/business identity, WRITE에서는 approval/idempotency/reconciliation identity 역할을 한다.

# 4. Context Projection

금지:

```text
AgentContext JSON → direct copy → NSL runtime_context
```

허용:

```text
AgentContext
→ deterministic Compiler binding
→ typed compiled inputs + explicit resource refs
→ bounded trace/provenance metadata
→ NSL ExecutionRequest
```

# 5. Artifact Admission

```text
exact skill_id/version
→ exact NSP/package lookup
→ package/version/semantic binding verification
→ Signed NSP verification
→ PackageTrustEvidence
→ VerifiedSkillArtifact
→ NSL RuntimeEngine
```

`Certified/Enabled`와 `PackageTrustEvidence`는 별도 required controls이다. Silent version substitution 금지.

# 6. Approval / Suspend / Resume

NSL STRICT WRITE:

```text
WriteIntent Freeze
→ ApprovalRequestId
→ NSL Checkpoint
→ ApprovalPort.publish
→ WAITING_FOR_APPROVAL / StatementSuspended
```

Agent mapping:

```text
WAITING_FOR_APPROVAL
→ StepExecutionOutcome.WAITING
→ AgentExecution.WAITING_APPROVAL
→ WaitRegistration(wait_source=NSL_APPROVAL)
→ Worker Release
```

Human workflow와 Resume scheduling은 Agent/Platform 책임이다.

Agent `FORMAL_APPROVAL`은 NSL WRITE Approval의 대체물이 아니다.

Resume bridge 최소 필드:

```text
agent_execution_id
executable_step_id
nsl_execution_id
business_operation_id
approval_request_id
nsl_checkpoint_version
event_id
correlation_id
approval_evidence_ref/payload
```

# 7. Idempotency / Retry

Agent/Platform:
```text
BusinessOperationId owner
```

NSL Runtime:
```text
TenantId + BusinessOperationId + WriteNodeId
→ actual IdempotencyKey
```

Agent Compiler는 LOCAL_SKILL의 actual NSL WRITE key를 생성하지 않는다.

Retry:
```text
same BusinessOperationId
→ NSL derives same key
```

`UNKNOWN_COMMIT_STATE`는 blind retry 금지.

# 8. Reconciliation Evidence

```text
NSLReconciliationEvidence
├─ nsl_execution_id
├─ business_operation_id
├─ write_node_id
├─ tool_id
├─ tool_invocation_id
├─ idempotency_key
├─ payload_hash
├─ write_intent_hash
├─ provider_transaction_id
├─ business_reference
├─ verification_hint
├─ failure_evidence_ref
└─ write_evidence_ref
```

Agent/Platform이 action을 결정하고 scheduling한다.

# 9. Security Control Composition

```text
Current OA Authorization
AND required EA Operation Trust
AND Skill Governance
AND Kill-switch clear
AND Package Trust valid
AND required NSL CHECK PASS
AND required NSL Approval valid
AND current NSL PolicyDecision ALLOW
AND Write-time Business Preconditions PASS
```

어떤 ALLOW도 다른 required control의 DENY/INVALID를 override하지 않는다.

Canonical naming:
- `operation_trust_decision`
- `package_trust_evidence`

generic `trust` 사용 금지.

# 10. EA-Trust ↔ Actual WRITE Binding

`operation_fingerprint`를 NSL `PayloadHash`와 동일시하지 않는다.

Integration Layer는 기존 NSL `WriteExecutionPort`를 구현하는 governed wrapper를 제공한다.

```text
NSL Runtime
→ GovernedWriteExecutionPort
→ actual WriteCallRequest
   + ProtectedOperationDescriptor
   + OperationTrustDecision
→ conformance validation
→ PASS: Provider WriteExecutionPort
→ FAIL: Provider WRITE = 0
```

# 11. Result Mapping

```text
NSL ExecutionResult
→ NSLResultMapper
→ NSLResultSummary
→ StepExecutionOutcome + StepResult
```

핵심 규칙:
- `WAITING_FOR_APPROVAL` → `WAITING`
- `UNKNOWN_COMMIT_STATE` → `RECONCILIATION_REQUIRED`
- `COMMITTED + Verification FAILED/UNKNOWN` → WRITE 재시도 금지
- Approval REJECTED → business `BLOCKED`, technical retry 아님
- `NOT_COMMITTED` retry는 RetrySafety + Agent policy가 모두 허용할 때만

# 12. Evidence / Audit

NSL:
- detailed execution/write evidence SoR

Agent:
- semantic step/result/history SoR

Agent는 NSL raw journal을 복제하지 않고:
- stable ref
- hash
- classification
- minimal semantic summary

로 연결한다.

E2E chain:

```text
correlation_id
→ AgentExecutionId
→ ExecutableStepId
→ NSLExecutionId
→ BusinessOperationId
→ WriteNodeId
→ ToolInvocationId
→ BusinessReference
→ StepResultId
→ AgentResultId
→ PublicationOperationId
```

# 13. Production Admission

Required Agent-level controls가 있는 Production WRITE는 governed integration path를 통과해야 한다. Direct NSL caller를 허용할 경우 동일한 Control Contract/WriteExecutionPort wrapper를 구현해야 한다.

# 14. Normative Invariants

1. Agent FORMAL_APPROVAL != NSL WRITE Approval
2. AgentExecutionId != NSLExecutionId
3. AgentContext 전체를 NSL에 전달하지 않는다.
4. Agent Compiler는 actual NSL WRITE IdempotencyKey를 생성하지 않는다.
5. Trust ALLOW != OA ALLOW != Package Trust Valid.
6. COMMITTED + Verification FAILED는 WRITE 실패가 아니다.
7. UNKNOWN_COMMIT_STATE는 blind retry하지 않는다.
8. Publication retry는 Business WRITE를 재실행하지 않는다.
