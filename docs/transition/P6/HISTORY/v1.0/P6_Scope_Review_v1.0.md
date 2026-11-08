# P6 NSL READ Integration Scope Review v1.0

**Status:** PRE-IMPLEMENTATION SCOPE REVIEW

---

## 1. Scope Statement

P6 is not "implement NSL v0.2".

P6 is:

> Connect the completed P5 Agent Runtime to deterministic NSL READ execution through a v0.2-compatible AE integration contract.

Current backend may be NSL v0.1.

---

## 2. Why the filename is version-neutral

Using only `v0.1` in the title would incorrectly make the AE integration contract a legacy implementation detail.

Using only `v0.2` would imply the runtime is already implemented.

Therefore:

```text
P6_NSL_READ_Integration_SRS_v1.0.md
```

is the stable phase name.

---

## 3. P6 Functional Center

```text
LOCAL_SKILL ExecutableStep
→ exact Skill Artifact
→ NSL deterministic READ
→ StepResult
```

Worker/dispatcher/timeline work exists to make this path operationally valid.

---

## 4. P6 Does Not Pull v0.2 WRITE Forward

Although the Frozen integration request contains future fields and NSL v0.2 includes Controlled WRITE, P6 activates READ only.

Forbidden implementation in P6:

```text
WRITE
Approval
Checkpoint Approval Resume
IdempotencyKey for WRITE
CommitState
VerificationStatus
UNKNOWN_COMMIT_STATE
```

---

## 5. BusinessOperationId Clarification

BusinessOperationId is not synonymous with WRITE.

Frozen integration requires it for READ too.

P6 must therefore distinguish:

```text
BusinessOperationId
= stable semantic NSL operation identity

operation_fingerprint
= later WRITE trust/operation descriptor concept
```

P6 READ uses the first and not the second.

---

## 6. P5 Contract Compatibility

P5 historical results remain valid.

P6 introduces a conditional evolution:

```text
P5 non-NSL StepResult
→ BusinessOperationId null

P6 LOCAL_SKILL READ StepResult
→ BusinessOperationId non-null
```

This must be versioned/controlled, not silently changed.

---

## 7. v0.1 Backend Boundary

P6 may reuse v0.1:

- `VerifiedPackageSkillResolver`;
- `SkillExecutionJob`;
- `SkillExecutionWorker`;
- `RuntimeResultEnvelope`;
- READ RuntimeEngine;
- process-isolation adapter.

But AE code must depend on a P6 backend port/facade rather than importing broad private NSL internals.

---

## 8. Worker Scope

P6 worker is production foundation, not full orchestration platform.

Required:

- process lifecycle;
- tenant dispatcher;
- lease-safe claim;
- executor dispatch;
- observability.

Deferred:

- autoscaling control plane;
- sophisticated priorities;
- heterogeneous fleet optimization;
- CA/PA/EA assignment.

---

## 9. E2E Definition

A P6 E2E is not complete merely because an NSL unit test passes.

It must begin from the Agent execution path and prove:

```text
AgentPlan
→ LOCAL_SKILL
→ AE RuntimeJob/Worker
→ verified NSP
→ NSL READ
→ StepResult
→ AgentResult
```

---

## 10. Closure Statement

Correct P6 closure statement:

> **P6 NSL READ Integration — AE Worker + v0.2-compatible request + verified artifact + NSL READ + StepResult E2E CLOSED**

Incorrect:

> NSL v0.2 implementation complete.
