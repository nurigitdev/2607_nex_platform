# P6-S3 NSLStepExecutionBinding and SkillExecutionRequest

**Status:** COMPLETE
**Date:** 2026-10-14
**Predecessor:** P6-S2 Skill Artifact Gateway
**Next:** P6-S4 LOCAL_SKILL Activation

## Purpose

P6-S3 establishes the durable AE boundary between one compiled local-Skill
step and a future NSL backend invocation.

```text
ExecutableStep + VerifiedSkillArtifact + bounded trusted context
-> stable NSLExecutionId + BusinessOperationId
-> canonical SkillExecutionRequest
-> immutable request-bound NSLStepExecutionBinding
```

No NSL process is invoked in this Slice. The RuntimeJob remains scheduling
authority, and `LOCAL_SKILL` remains unavailable until P6-S4.

## Source and Refactoring Audit

The existing P5/P6 ownership boundaries remain coherent:

- `ae_runtime_job` owns durable scheduling, leases, and attempts;
- `ae_executable_step` owns compiled step identity and state;
- `ae_nsl_artifact` owns the bounded verified package/trust projection; and
- `ae_step_result` owns immutable terminal semantic results.

Therefore no new queue, worker, or broad package move was introduced. The new
binding is a narrow pre-invocation identity/request record, not another work
queue.

## Binding and Request Semantics

Migration `2202_ae_nsl_step_execution` adds `ae_nsl_step_execution` with one
row per `(tenant_id, executable_step_id)`. It stores:

- distinct NSL execution and BusinessOperation UUIDs;
- Agent execution, executable plan/step, and AgentContext lineage;
- exact Skill/version/semantic hash and verified artifact reference/hash;
- canonical request reference/hash and bounded request JSON;
- bounded context projection JSON;
- selected `NSL_V01_PROCESS_ISOLATED` backend profile; and
- binding state and lifecycle timestamps/result references.

All table, constraint and index names are 30 characters or fewer. Foreign
keys remain inside the AE database boundary.

The repository checks the persisted step is a planned `LOCAL_SKILL`, accepts
the current pre-S4 `LOCAL_SKILL_UNAVAILABLE` executor only for binding, and
requires exact capability/version equality with the persisted verified
artifact. It also resolves the latest persisted AgentContext for the same
execution and verifies its reference, hash, and tenant against the bounded
projection.

The request contains only validated compiled inputs, exact provenance,
explicit resource references, authority/policy references and hashes. Full
AgentContext, raw prompt/content, credentials, secrets and provider material
are rejected recursively. Retry or worker restart returns the same binding;
changed immutable input fails closed.

## StepResult Compatibility

The existing writer/reader now dispatches explicitly by schema version:

```text
schema 1.1 (historical P5)
  executor_kind absent
  business_operation_id = null
  operation_fingerprint = null

schema 1.2 (P6)
  executor_kind required
  LOCAL_SKILL -> business_operation_id = UUID
  other executor -> business_operation_id = null
  operation_fingerprint = null
```

Migration 2202 adds the nullable `executor_kind` column and compatible JSON
checks without rewriting historical 1.1 rows.

## Verification

Focused S3 and StepResult tests:

```text
70 passed
nsl_step_executions.py statement/branch coverage: 100% / 100%
step_results.py statement/branch coverage: 100% / 100%
```

P5/P6 explicit regression:

```text
225 passed
```

AE Slice Gate with all P5/P6 tests explicitly included:

```text
3694 passed, 5 protected opt-in tests skipped
statement coverage: 98.67% (previous 98.65%)
branch coverage: 96.95% (previous 96.89%)
contract validation: PASS
  schemas: 174
  examples: 236
  negative examples: 204
  OpenAPI documents: 7
```

Actual `nex_ae_test` protected PostgreSQL smoke:

```text
database: nex_ae_test
role: nex_ae_user
41 migrations current
latest migration: 2202_ae_nsl_step_execution
checks: 20/20 PASS
binding rows exercised: 1
remaining S3 rows after cleanup: 0
```

The smoke creates real P5 execution/plan/context lineage, materializes the
verified artifact, converts one planned step to the pre-S4 local-Skill shape,
performs binding insert/select and restart replay, rejects an immutable-input
change, verifies stable distinct IDs, and cleans all S3 data.

Generation, embedding, reranking, and the NSL runtime process are not required
for this Slice.
