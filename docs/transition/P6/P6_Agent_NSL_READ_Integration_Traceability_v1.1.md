# P6 Agent ↔ NSL READ Integration Traceability v1.1

**Status:** P6-S7 E2E-01 EVIDENCE COMPLETE

## 1. Identity chain

```text
correlation_id
→ AgentExecutionId
→ ExecutablePlanId
→ ExecutableStepId
→ NSLStepExecutionBinding
→ NSLExecutionId
→ BusinessOperationId
→ NSL ToolInvocationId(s)
→ StepResultId
→ AgentResultId
→ ResultDeliveryId
```

P6 READ has no WriteNodeId, WRITE IdempotencyKey or CommitState.

## 2. Responsibility trace

| Concern | Owner |
|---|---|
| AgentExecution / Plan / Step | AE |
| NSLExecutionId allocation/persistence | AE Integration |
| NSLExecutionId runtime lifecycle semantics | NSL Runtime |
| BusinessOperationId allocation/persistence | AE Integration |
| RuntimeJob / lease / attempt | AE |
| Worker/dispatcher | AE |
| Artifact lookup orchestration | Skill Artifact Gateway |
| Package/signature verification | NSL package/security boundary |
| LOCAL_SKILL executor | AE |
| deterministic READ execution | NSL |
| StepResult / AgentResult | AE |
| detailed NSL audit | NSL |
| timeline projection | AE protected operations surface |

## 3. Request mapping

| Canonical field | v0.1 backend |
|---|---|
| agent_execution_id | AE binding only |
| executable_plan_id | AE binding only |
| executable_step_id | AE binding only |
| nsl_execution_id | `SkillExecutionJob.execution_id` |
| business_operation_id | AE binding/timeline; v0.1 does not natively consume |
| skill_id | skill_id |
| exact_skill_version | skill_version |
| semantic hash | expected_semantic_hash |
| compiled inputs | StructuredInputs |
| input provenance | InputProvenance |
| principal | VerifiedPrincipalContext |
| data policy/classification | ExplicitDataHandlingPolicy + bounded context |
| context ref/hash | AE binding + bounded runtime context |
| correlation/causation | AE RuntimeJob/timeline |
| mode=NEW | ordinary v0.1 execute |

## 4. StepResult trace

```text
P5 historical result
schema=1.1
BOI=null
operation_fingerprint=null

P6 LOCAL_SKILL READ result
schema=1.2
BOI=stable non-null
operation_fingerprint=null
```

## 5. Claim trace

```text
worker capability declaration
→ dispatcher leader
→ candidate job
→ referenced step executor_kind
→ capability eligibility
→ lease CAS
```

All occur under one claim transaction for the final eligibility/update boundary.

## 6. Timeline trace

Projection ordering:

```text
event_time
phase_order
source_type_order
stable_source_id
```

Only canonical persisted/evidence-backed transitions are shown. Unknown optional historical state remains null.

## 7. Future WRITE preservation

P6 establishes:

```text
NSLExecutionId
BusinessOperationId
```

but not:

```text
WriteNodeId
ApprovalRequestId
IdempotencyKey
PayloadHash for WRITE
CommitState
VerificationStatus
```

Future phases extend rather than rename P6 identities.

## 8. P6-CA01 evidence

```text
P6_CA01_Source_Backed_READ_Contract_Closure_v1.0.md
contracts/*.schema.json
contracts/examples/p6-golden-*.json
tests/test_ae_p6_ca01_read_contracts.py
```

This evidence closes contract traceability only. Runtime implementation and
PostgreSQL evidence remain assigned to P6-S0 through P6-S7.

## 9. P6-S0 worker evidence

```text
source:
  services/nex-ae-api/nex_ae_api/agent_runtime_worker.py

tests:
  tests/test_ae_p6_s0_agent_runtime_worker.py
  tests/test_ae_p6_s0_postgres_smoke.py

protected runner:
  scripts/smoke/run_p6_s0_postgres_smoke.py
```

Trace boundary:

```text
worker capability profile/hash
→ startup implementation admission
→ PostgreSQL heartbeat STARTING/IDLE/BUSY/STOPPING/STOPPED
→ injected RuntimeJob assignment
→ active-claim accounting
→ lease-authority-preserving handler success/failure
→ restart with no process-local work authority
```

P6-S0 does not claim tenant discovery, dispatcher leadership, fairness,
capability-aware SQL candidate filtering or atomic claim. P6-S1 closes those
boundaries with the evidence below.

## 10. P6-S1 dispatcher evidence

```text
source:
  database/nex-ae-api/migrations/2200_ae_runtime_dispatch.sql
  services/nex-ae-api/nex_ae_api/agent_runtime_dispatcher.py
  services/nex-ae-api/nex_ae_api/agent_runtime_operations.py
  services/nex-ae-api/nex_ae_api/runtime_jobs.py

tests:
  tests/test_ae_p6_s1_agent_runtime_dispatcher.py
  tests/test_ae_p6_s1_agent_runtime_operations.py
  tests/test_ae_p6_s1_postgres_smoke.py

protected runner:
  scripts/smoke/run_p6_s1_postgres_smoke.py
```

Trace boundary:

```text
DB leader lease + fencing token
→ bounded durable tenant snapshot
→ worker executor/backend eligibility
→ executor-filtered RuntimeJob lease CAS
→ bounded assignment source
→ worker lifecycle
```

Actual `nex_ae_test` evidence passed 19/19 checks, including concurrent leader
exclusivity, failover, stale-leader fencing, capability filtering, lease
reclaim, malformed-job reconciliation, AG read-only projection and zero
residue. No remote provider is involved in this Slice.

## 11. P6-S2 Skill Artifact Gateway evidence

```text
source:
  database/nex-ae-api/migrations/2201_ae_nsl_artifact.sql
  services/nex-ae-api/nex_ae_api/skill_artifacts.py

tests:
  tests/test_ae_p6_s2_skill_artifacts.py
  tests/test_ae_p6_s2_postgres_smoke.py

protected runner:
  scripts/smoke/run_p6_s2_postgres_smoke.py
```

Trace boundary:

```text
exact Skill ID/version + expected semantic hash
-> public NSL verified-package resolver shape
-> exact package hash + verified signing key
-> tenant-scoped current trust/admission source
-> VALID + ACTIVE + ADMITTED
-> bounded canonical VerifiedSkillArtifact
-> immutable ae_nsl_artifact row
```

The persisted artifact retains only opaque package/evidence/admission
references and hashes. Raw package, NSO, signature and verification-journal
content remain outside AE persistence. Actual `nex_ae_test` evidence passed
14/14 checks with restart-style reload, tenant isolation, fail-closed negative
paths, zero forbidden residue and cleanup to zero rows.

## 12. P6-S3 request and identity binding evidence

```text
source:
  database/nex-ae-api/migrations/2202_ae_nsl_step_execution.sql
  services/nex-ae-api/nex_ae_api/nsl_step_executions.py
  services/nex-ae-api/nex_ae_api/step_results.py

tests:
  tests/test_ae_p6_s3_nsl_step_execution.py
  tests/test_ae_p6_s3_postgres_smoke.py

protected runner:
  scripts/smoke/run_p6_s3_postgres_smoke.py
```

Trace boundary:

```text
planned LOCAL_SKILL step
-> exact persisted VerifiedSkillArtifact
-> trusted bounded AgentContext projection
-> stable NSLExecutionId + BusinessOperationId
-> canonical SkillExecutionRequest hash
-> immutable request-bound ae_nsl_step_execution row
-> restart/retry reload of the same identities
```

Actual `nex_ae_test` evidence passed 20/20 checks, including migration
currency, P5 upstream lineage creation, binding insert/select, restart replay,
immutable-conflict rejection, distinct stable IDs and cleanup to zero rows.
S3 does not activate the executor or invoke NSL; those remain S4 and S5.

## 13. P6-S4 LOCAL_SKILL activation evidence

```text
source:
  database/nex-ae-api/migrations/2203_ae_local_skill_activation.sql
  services/nex-ae-api/nex_ae_api/planning_capabilities.py
  services/nex-ae-api/nex_ae_api/executable_plans.py
  services/nex-ae-api/nex_ae_api/step_executors.py

tests:
  tests/test_ae_p6_s4_local_skill_activation.py
  tests/test_ae_p6_s4_postgres_smoke.py

protected runner:
  scripts/smoke/run_p6_s4_postgres_smoke.py
```

Trace boundary:

```text
exact LOCAL_SKILL capability descriptor
-> P6 capability snapshot 1.2
-> deterministic executable plan 1.2
-> persisted exact skill_binding_json
-> dependency-complete P6LocalSkillExecutor
-> registry-derived worker capability/backend readiness
```

Actual `nex_ae_test` evidence passed 19/19 checks, including migration
currency, real snapshot/plan/step insert and reload, exact local-Skill binding,
startup readiness, partial-composition rejection, no backend invocation, and
cleanup to zero rows. P6-S5 owns the first NSL READ backend invocation.

## 14. P6-S5 NSL READ backend evidence

```text
source:
  database/nex-ae-api/migrations/2204_ae_nsl_backend_run.sql
  services/nex-ae-api/nex_ae_api/nsl_read_backends.py
  services/nex-ae-api/nex_ae_api/nsl_step_executions.py

tests:
  tests/test_ae_p6_s5_nsl_read_backend.py
  tests/test_ae_p6_s5_postgres_smoke.py

protected runner:
  scripts/smoke/run_p6_s5_postgres_smoke.py
```

Trace boundary:

```text
durable NSLStepExecutionBinding
-> exact VerifiedSkillArtifact
-> bounded SkillExecutionRequest and ContextProjection
-> stable nsl.api SkillExecutionJob
-> spawned v0.1 SkillExecutionWorker
-> terminal RuntimeResultEnvelope
-> ordered progress and audit/snapshot evidence bridge
-> immutable ae_nsl_backend_run attempt record
```

Actual `nex_ae_test` evidence passed 26/26 checks against 43 current
migrations and exact clean NSL revision `803f22aadc3946a48b05472c80b60fe11d9d9554`.
It executed the signed golden READ package, retained one restart-safe attempt,
bridged four progress events and 26 evidence references, isolated a real
timeout and non-zero child crash, preserved the parent DB session, and cleaned
all S5 rows. P6-S6 subsequently closed result summary, StepResult and timeline
projection with the evidence below.

## 15. P6-S6 result and timeline evidence

```text
source:
  services/nex-ae-api/nex_ae_api/nsl_result_integration.py
  services/nex-ae-api/nex_ae_api/agent_execution_timeline.py
  services/nex-ae-api/nex_ae_api/nsl_step_executions.py
  services/nex-ae-api/nex_ae_api/multi_step_engine.py
  services/nex-ae-api/nex_ae_api/step_executors.py

tests:
  tests/test_ae_p6_s6_result_timeline_integration.py
  tests/test_ae_p6_s6_postgres_smoke.py

protected runner:
  scripts/smoke/run_p6_s6_postgres_smoke.py
```

Trace boundary:

```text
terminal ae_nsl_backend_run evidence
-> bounded NSLResultSummary
-> terminal ae_nsl_step_execution summary ref/hash
-> StepExecutionOutcome
-> LOCAL_SKILL StepResult v1.2
-> deterministic timeline over retained canonical AE sources
```

Actual `nex_ae_test` evidence passed 20/20 checks against 43 current
migrations and exact clean NSL revision `803f22aadc3946a48b05472c80b60fe11d9d9554`.
It persisted one StepResult v1.2, projected 21 ordered events with three
explicit source gaps, reproduced the same projection after repository restart,
excluded raw runtime/private content, and cleaned all S6/P5 rows. Source audit
proved that migration `2205` and a separate timeline SoR are not required.

## 16. P6-S7 IA READ end-to-end evidence

```text
source:
  services/nex-ae-api/nex_ae_api/p6_ia_read_runtime.py

tests:
  tests/test_ae_p6_s7_ia_read_runtime.py
  tests/test_ae_p6_s7_postgres_smoke.py

protected runner:
  scripts/smoke/run_p6_s7_postgres_smoke.py
```

Trace boundary:

```text
IA prompt/planning records
-> LOCAL_SKILL RuntimeJob
-> DB-leased dispatcher and capability-aware assignment
-> bounded Agent Runtime worker
-> exact artifact/request/NSL READ/result composition
-> LOCAL_SKILL StepResult v1.2
-> dependent deterministic StepResult
-> AgentResult + ResultDelivery(PENDING)
-> deterministic timeline and restart dedup
```

Actual `nex_ae_test` evidence passed 23/23 checks against 43 current
migrations and exact NSL revision `803f22aadc3946a48b05472c80b60fe11d9d9554`.
It retained two RuntimeJobs/attempts and StepResults, one NSL execution,
AgentResult and pending delivery, projected 29 events, reproduced result and
timeline state after restart, excluded raw runtime content and cleaned all
rows. The AE/P5/P6 gate passed 3812 tests with statement 98.66% and branch
96.88% coverage.
