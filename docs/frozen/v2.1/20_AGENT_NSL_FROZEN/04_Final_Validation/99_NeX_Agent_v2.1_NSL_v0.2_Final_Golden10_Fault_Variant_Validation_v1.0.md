# NeX Agent v2.1 ↔ NSL v0.2
# Final Golden 10 + Fault Variant Architecture Validation v1.0

**상태:** FINAL E2E ARCHITECTURE VALIDATION — PASS  
**대상:** NeX Agent v2.1 Final Consistency Closure v1.1 + NSL v0.2 Frozen + Integration Contract v1.0  
**주의:** 본 검증은 설계/계약 수준 Architecture Validation이며, 아직 Source Code를 실행한 Runtime Test 결과는 아니다.

---

# 1. Executive Verdict

Golden 10과 필수 Fault Variant를 Agent↔NSL 전체 경계에 다시 적용한 결과:

```text
Golden Scenario 10 / 10 PASS
Fault Variant    6 / 6 PASS
```

따라서 Cross-Architecture 관점의 기존 P0/P1/ICG는 모두 닫힌 것으로 판정한다.

```text
P0  = 0
P1  = 0
ICG = 0
```

---

# 2. GS-01 — IA → NSL READ

**Verdict: PASS**

```text
User
→ IA
→ Intent / Context / Plan
→ deterministic Compile
→ exact LOCAL_SKILL binding
→ SkillExecutionRequest
→ exact Artifact resolution
→ VerifiedSkillArtifact
→ NSL ExecutionRequest
→ READ
→ ExecutionResult
→ StepResult
→ AgentResult
```

검증:

- READ 포함 모든 NSL invocation에 stable BusinessOperationId 공급
- AgentExecutionId ≠ NSLExecutionId
- explicit TenantId
- AgentContext 전체 전달 금지
- typed compiled inputs/resource refs만 projection
- READ는 WRITE Approval flow를 시작하지 않음

---

# 3. GS-02 — NSL STRICT WRITE without prior Approval

**Verdict: PASS — Negative Safety Scenario**

```text
LOCAL_SKILL NEW
→ NSL CHECK
→ PreWriteEligibility = REQUIRES_APPROVAL
→ WriteIntent Freeze
→ ApprovalRequestId
→ Checkpoint
→ WAITING_FOR_APPROVAL
→ Agent WAITING_APPROVAL
→ Worker Release
```

Expected:

```text
Provider WRITE count = 0
```

Agent A06/A07/A10과 NSL v0.2 contract가 일치한다.

---

# 4. GS-03 — Approval → Suspend → Resume → WRITE

**Verdict: PASS**

```text
NSL NEW
→ ApprovalRequest
→ StatementSuspended
→ AE NSL_APPROVAL WaitRegistration
→ Worker Release

Human Decision
→ Event dedup/match
→ NSLApprovalResumeValidator
→ ResumeToken
→ current OA/kill-switch/policy refresh
→ NSL RESUME
→ ApprovalEvidence binding
→ current PolicyDecision
→ write-time Preconditions
→ WRITE
```

검증 identity:

```text
NSLExecutionId
BusinessOperationId
ApprovalRequestId
checkpoint_version
ApprovalEvidence
```

모두 stable/bound.

---

# 5. GS-04 — CA → WC → Child Agent → NSL WRITE

**Verdict: PASS**

```text
Parent DELEGATE_WORK
→ WC Pool WorkItem
→ atomic claim
→ assignment materialization
→ Child AgentExecution
→ Child Plan/Compile
→ LOCAL_SKILL
→ NSL controlled WRITE
→ Child AgentResult / WC WorkResult
→ Parent Resume
```

검증:

- Claim 전 Child START 금지
- Parent는 Claim Event가 아니라 WorkResult를 기다림
- Child도 동일 Agent↔NSL Integration Contract 사용
- actual NSL key는 Child Agent가 생성하지 않음

---

# 6. GS-05 — PA Multi-step + Delegation + NSL

**Verdict: PASS**

v2.1 baseline:

```text
Option A Sequential WAIT
```

```text
PA
→ Child CA Work
→ WAIT/Resume
→ Child EA Work
→ WAIT/Resume
→ optional LOCAL_SKILL
→ AGGREGATE
→ Completion Verification
→ AgentResult
```

Agent collaboration과 NSL atomic execution boundary가 분리되어 충돌하지 않는다.

---

# 7. GS-06 — EA-Trust ALLOW + OA DENY

**Verdict: PASS**

```text
EA Operation Trust = ALLOW
Current OA Authorization = DENY
```

결과:

```text
BLOCK
Provider WRITE = 0
```

원칙:

```text
Trust ALLOW
does not override
OA DENY
```

NSL actual WRITE 직전 current PolicyDecision도 별도 fail-closed control이다.

---

# 8. GS-07 — UNKNOWN_COMMIT_STATE → Reconciliation

**Verdict: PASS**

```text
durable WRITE_REQUESTED
→ Provider ambiguity
→ UNKNOWN_COMMIT_STATE
→ NSL RECONCILIATION_REQUIRED
→ Agent StepOutcome RECONCILIATION_REQUIRED
→ RECONCILE_EXECUTION
→ authoritative SoR query
```

금지:

```text
blind retry
new BusinessOperationId
new arbitrary key
```

`CONFIRMED_NOT_COMMITTED`일 때만 동일 BusinessOperationId로 retry 가능하며 actual key는 NSL이 재도출한다.

---

# 9. GS-08 — Duplicate RuntimeJob → Duplicate WRITE 방지

**Verdict: PASS**

```text
duplicate Agent RuntimeJob
→ same logical LOCAL_SKILL
→ same BusinessOperationId
→ NSL derives same TenantId + BusinessOperationId + WriteNodeId key
```

동일 payload:

```text
original/idempotent result
```

다른 payload:

```text
IDEMPOTENCY_CONFLICT
```

Agent가 actual NSL key를 생성하지 않으므로 cross-layer key drift가 없다.

---

# 10. GS-09 — COMMITTED + Verification FAILED

**Verdict: PASS**

```text
CommitState = COMMITTED
VerificationStatus = FAILED
```

Agent mapping:

```text
Side Effect lifecycle = terminal
Business WRITE retry = 0
Verification evidence preserved
Agent Completion Verification
→ FAILED / PARTIAL / CONFLICT 가능
```

`CommitState ≠ VerificationStatus`가 유지된다.

---

# 11. GS-10 — Result Publication Unknown

**Verdict: PASS**

```text
Business WRITE already COMMITTED
→ AgentResult publication request
→ ACK lost / UNKNOWN_DELIVERY
```

처리:

```text
Publication-specific retry/reconciliation
```

금지:

```text
Business WRITE 재실행
```

따라서:

```text
Business WRITE count = 1
```

---

# 12. Fault Variant FV-01 — Invalid / Missing Package Trust

**Verdict: PASS**

```text
Agent Plan valid
OA ALLOW
exact skill/version selected
but Signed NSP trust invalid/missing
```

Agent:

```text
exact NSP resolve / verify
→ VerifiedSkillArtifact required
```

NSL:

```text
Production WRITE
→ valid PackageTrustEvidence required
```

결과:

```text
Provider WRITE = 0
```

---

# 13. Fault Variant FV-02 — Approval Replay / Binding Mismatch

**Verdict: PASS**

Variant:

```text
old ApprovalRequestId
or different BusinessOperationId
or PayloadHash changed
or WriteIntentHash changed
```

NSL validation supports:

```text
APPROVAL_REQUEST_MISMATCH
BUSINESS_OPERATION_MISMATCH
PAYLOAD_MISMATCH
INTENT_MISMATCH
```

A07 Resume bridge preserves relevant identity/binding fields.

결과:

```text
WRITE = 0
```

---

# 14. Fault Variant FV-03 — EA-Trust Fingerprint != Actual WRITE

**Verdict: PASS**

```text
OA = ALLOW
EA Operation Trust = ALLOW for descriptor A
actual NSL WriteCallRequest = operation B
A != B
```

Provider 호출 직전:

```text
GovernedWriteExecutionPort
→ ProtectedOperationDescriptor conformance
```

Mismatch:

```text
BLOCK
Provider WRITE = 0
```

---

# 15. Fault Variant FV-04 — Same Key Domain + Different Payload

**Verdict: PASS**

NSL:

```text
same IdempotencyKey
+ different PayloadHash
→ IDEMPOTENCY_CONFLICT
```

PayloadHash를 key 생성 input으로 사용해 conflict detection을 우회하지 않는다.

---

# 16. Fault Variant FV-05 — Verification Failure after Commit

**Verdict: PASS**

```text
COMMITTED
→ Post-write Verification FAILED/UNKNOWN
```

결과:

```text
WRITE retry = 0
commit state remains COMMITTED
verification result propagates to Agent Completion Verification
```

---

# 17. Fault Variant FV-06 — Publication ACK Lost

**Verdict: PASS**

```text
NSL Business WRITE = COMMITTED
AgentResult publication
→ ACK lost
```

결과:

```text
Publication reconciliation only
Business WRITE count remains 1
```

---

# 18. Final Control Composition Re-check

Protected NSL WRITE의 최종 control은 다음 conjunction으로 유지된다.

```text
Current OA Authorization
AND
required EA Operation Trust
AND
Skill Governance / Kill-switch
AND
Verified Package Trust
AND
required NSL CHECK
AND
required NSL Approval
AND
current NSL PolicyDecision
AND
write-time Business Preconditions
AND
Idempotency / Commit Safety
```

어느 하나의 ALLOW도 다른 required control의 DENY/INVALID를 override하지 않는다.

---

# 19. Final Identity Re-check

```text
AgentExecutionId
!=
NSLExecutionId

BusinessOperationId
= Agent/Platform stable semantic operation identity

IdempotencyKey
= NSL Runtime-owned actual WRITE identity

ApprovalRequestId
= NSL Runtime approval request instance

RuntimeJobId
!= BusinessOperationId
!= IdempotencyKey
```

---

# 20. Final E2E Audit Chain

```text
correlation_id
→ AgentExecutionId
→ ExecutableStepId
→ NSLExecutionId
→ BusinessOperationId
→ WriteNodeId
→ ToolInvocationId
→ BusinessReference
→ StepResult
→ AgentResult
→ PublicationOperation
```

Detailed NSL evidence remains NSL SoR; Agent retains stable ref/hash/semantic projection.

---

# 21. Verdict

```text
Golden 10     = 10 / 10 PASS
Fault Variant =  6 /  6 PASS

P0  = 0
P1  = 0
ICG = 0
```

따라서 Architecture/Contract 수준에서:

> **NeX Agent v2.1 ↔ NSL v0.2 INTEGRATION CONSISTENCY — CLOSED**

최종 Freeze 선언 가능.
