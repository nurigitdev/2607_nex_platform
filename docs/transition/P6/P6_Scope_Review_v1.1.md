# P6 NSL READ Integration Scope Review v1.1

**Status:** P6-CA01A CONSOLIDATED SCOPE
**Supersedes:** v1.0

## 1. P6 is not NSL v0.2 implementation

P6 connects completed P5 Agent Runtime to deterministic NSL READ through a v0.2-compatible AE integration contract.

Current backend may remain v0.1.

## 2. Functional center

```text
LOCAL_SKILL ExecutableStep
→ exact verified Skill artifact
→ canonical SkillExecutionRequest
→ NSL deterministic READ
→ NSLResultSummary
→ StepResult v1.2
```

Worker/dispatcher/timeline work makes this path operationally valid.

## 3. No P6 Slice before CA01

CA01A withdrew the previous S0/S1 early-start allowance.

```text
CA01A → CA01 → S0 → S1 → ... → S7
```

## 4. BusinessOperationId is in scope

BusinessOperationId is required for READ as stable semantic operation identity.

It is not WRITE authority.

`operation_fingerprint` remains null.

## 5. StepResult version boundary

```text
P5 historical = 1.1
P6 current    = 1.2
```

No historical backfill/reinterpretation.

## 6. Worker/dispatcher scope

P6 includes:

- dedicated worker;
- homogeneous initial capability profile;
- capability-aware atomic claim;
- single dispatcher leader;
- deterministic bounded fairness;
- backpressure.

P6 excludes heterogeneous pool routing/autoscaling control plane.

## 7. Timeline scope

“Complete” means complete over retained canonical evidence, not invented history.

Missing `state_before/state_after` remains null.

No new timeline SoR unless S6 audit proves a required event cannot be projected.

## 8. Source availability

P6-CA01 must inspect the exact NSL checkout SHA in the implementation workspace. A particular local path is not a product-level requirement.

## 9. WRITE remains out

P6 does not implement approval, WRITE, IdempotencyKey, CommitState, VerificationStatus or UNKNOWN_COMMIT_STATE.

## 10. Closure statement

> **P6 NSL READ Integration — source-backed v0.2-compatible contract + AE worker/dispatcher + verified artifact + NSL READ + StepResult v1.2 E2E CLOSED**

Not:

> NSL v0.2 implementation complete.
