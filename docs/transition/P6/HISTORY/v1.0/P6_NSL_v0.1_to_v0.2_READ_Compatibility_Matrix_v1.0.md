# P6 NSL v0.1 → v0.2 READ Compatibility Matrix v1.0

**Status:** PRE-IMPLEMENTATION COMPATIBILITY BASELINE

---

## 1. Version Position

| Concern | NSL v0.1 As-Built | Frozen NSL v0.2 target | P6 decision |
|---|---|---|---|
| READ language/runtime | Implemented | preserved | reuse |
| WRITE | compile rejected | controlled WRITE | out of P6 |
| exact Tool Contract | implemented | preserved/extended | reuse |
| exact skill version | implemented | mandatory | reuse |
| NSP verification | implemented | required artifact boundary | reuse/harden projection |
| signature verification | implemented | required trust evidence | reuse |
| AE worker boundary | framework-neutral contract implemented | integration layer expanded | adapt |
| AgentExecutionId | not explicit in v0.1 job | explicit | AE keeps separately |
| NSLExecutionId | v0.1 `execution_id` | explicit distinct identity | map P6 NSLExecutionId → v0.1 execution_id |
| BusinessOperationId | absent | required on all invocations | P6 adds on AE side |
| ExecutablePlanId | absent in v0.1 job | explicit | P6 request envelope only |
| ExecutableStepId | absent in v0.1 job | explicit | P6 request envelope only |
| compiled inputs | v0.1 structured inputs | explicit compiled inputs | adapt |
| explicit resource refs | runtime_context can carry data | explicit refs | P6 projects explicitly |
| principal | verified principal implemented | explicit executing principal/business actor | reuse + map |
| data policy/classification | implemented | explicit classification/scope | reuse + map |
| org/project scope | generic runtime context/scopes | explicit fields | P6 typed projection |
| correlation/causation | not first-class in v0.1 job | explicit | P6 holds outside/backend metadata |
| AgentContext ref/hash | absent | explicit | P6 carries; backend receives bounded projection |
| package trust evidence | verified package object / signer/hash | PackageTrustEvidence / VerifiedSkillArtifact | adapter |
| result | RuntimeResultEnvelope | additive ExecutionResult → NSLResultSummary | mapper |
| wait/resume | not needed for READ | supported for WRITE | out of P6 |
| audit/snapshot | implemented | preserved | reuse |
| process isolation | implemented | preserved | optional production profile / reuse |

---

## 2. v0.1 READ Strengths Reused by P6

P6 SHALL reuse existing v0.1 guarantees:

```text
READ
→ exact registered Tool
→ exact parameter contract
→ authorization
→ typed request validation
→ timeout
→ structured result validation
→ output schema/hash validation
→ audit/provenance
```

And existing package trust:

```text
untrusted NSP
→ NspVerifier
→ signature/trust policy
→ VerifiedNspPackage
→ exact Skill resolution
```

---

## 3. v0.1 External Gaps P6 Can Close

v0.1 certification left external NeX-AE gaps:

### NSL-AE-004
Actual AE async dispatch/worker end-to-end was not available.

P6 closes this through:

```text
AE API
→ ae_runtime_job
→ dedicated AE Runtime Worker
→ LOCAL_SKILL executor
→ NSL worker/runtime
```

### NSL-AE-008
Runtime Result / LLM Explanation real AE separation was not end-to-end proven.

P6 SHALL preserve deterministic NSL result as authoritative evidence and keep any LLM explanation/synthesis outside NSL result semantics.

---

## 4. Adapter Rule

Initial P6 adapter:

```text
P6 SkillExecutionRequest
        ↓
V01ReadBackendAdapter
        ↓
NSL v0.1 SkillExecutionJob
        ↓
SkillExecutionWorker
        ↓
RuntimeResultEnvelope
        ↓
P6 NSLResultMapper
        ↓
NSLResultSummary
```

The adapter is not permitted to:

- collapse AgentExecutionId and NSLExecutionId;
- discard BusinessOperationId from AE trace;
- substitute skill versions;
- copy whole AgentContext;
- invent package trust;
- reinterpret a failed v0.1 RuntimeResult as success.

---

## 5. v0.2 Backend Switch Condition

A v0.2 READ backend may replace the v0.1 adapter when:

- current NSL v0.1 regression remains green;
- v0.2 preserves v0.1 READ behavior;
- v0.2 request/result contract conforms to Frozen integration;
- P6 E2E tests pass unchanged at the AE-facing contract.

Target:

```text
AE P6 contract unchanged
backend v0.1 adapter → backend v0.2 native
```
