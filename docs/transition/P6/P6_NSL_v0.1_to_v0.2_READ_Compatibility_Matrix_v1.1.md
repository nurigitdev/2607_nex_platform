# P6 NSL v0.1 → v0.2 READ Compatibility Matrix v1.1

**Status:** P6-CA01 SOURCE-BACKED COMPATIBILITY BASELINE

| Concern | NSL v0.1 As-Built | Frozen v0.2 target | P6 v1.1 decision |
|---|---|---|---|
| READ semantics | implemented | preserved | reuse |
| exact Tool Contract | implemented | preserved/extended | reuse |
| CHECK / EMIT | implemented | preserved | reuse |
| NSP verification | implemented | artifact admission boundary | reuse |
| signature verification | implemented | PackageTrustEvidence | reuse/project |
| exact Skill resolution | implemented | mandatory | reuse |
| AE worker boundary | framework-neutral Worker implemented | Agent/Integration expanded | adapt |
| AgentExecutionId | absent in v0.1 job | explicit | retained in AE binding |
| ExecutablePlanId | absent | explicit | retained in AE binding |
| ExecutableStepId | absent | explicit | retained in AE binding |
| NSLExecutionId | v0.1 `execution_id` | explicit distinct identity | AE allocates; maps to v0.1 execution_id |
| BusinessOperationId | absent | required on all invocations | AE allocates/persists before call |
| StepResult schema | not AE concern | Agent semantic result | P6 uses 1.2 for LOCAL_SKILL READ |
| compiled inputs | StructuredInputs | explicit compiled inputs | adapt |
| input provenance | implemented | explicit | reuse |
| explicit resource refs | generic runtime context possible | explicit | P6 bounded projection |
| Principal | verified principal | executing principal/business actor | reuse/map |
| data policy | implemented | classification/scope | reuse/map |
| org/project scope | generic scopes/context | explicit | P6 typed projection |
| correlation/causation | not first-class | explicit | AE binding/timeline |
| AgentContext ref/hash | absent | explicit | AE keeps, adapter projects bounded subset |
| package trust | VerifiedNspPackage/signature | VerifiedSkillArtifact/TrustEvidence | projection |
| result | RuntimeResultEnvelope | ExecutionResult→NSLResultSummary | mapper |
| wait/resume | not needed for READ | later WRITE use | out of P6 |
| audit/snapshot | implemented | preserved | refs/hashes reused |
| process isolation | implemented | compatible | CA01 selects production profile |

## v0.1 READ guarantees P6 must preserve

```text
exact registered Tool
→ parameter validation
→ authorization
→ typed request
→ timeout
→ structured result
→ schema/type/classification validation
→ result-hash verification
→ audit/provenance
```

## v0.1 external gaps P6 closes

### NSL-AE-004
Real AE async dispatch/worker end-to-end.

### NSL-AE-008
Real separation between deterministic runtime result and any LLM explanation/synthesis.

## Initial adapter

```text
P6 SkillExecutionRequest
→ V01ReadBackendAdapter
→ SkillExecutionJob
→ SkillExecutionWorker
→ RuntimeResultEnvelope
→ NSLResultMapper
→ NSLResultSummary
```

Canonical P6 fields that v0.1 does not natively consume remain durably preserved in AE `NSLStepExecutionBinding`.

## Backend switch condition

A native v0.2 READ backend may replace the v0.1 adapter only if:

- v0.1 READ regression remains compatible;
- Frozen request/result semantics are met;
- P6 AE-facing tests pass unchanged;
- no P6 identity renaming occurs.
