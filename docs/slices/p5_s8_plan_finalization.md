# P5-S8 Plan-Level Finalization

## Scope

- Verify the exact terminal StepResult set against the persisted
  ExecutablePlan and required completion criteria.
- Synthesize one immutable, reference-only plan-level AgentResult.
- Atomically create the existing required `WORKSPACE_RESULT` delivery in
  `PENDING` state.
- Preserve the publication ACK barrier: a successful execution remains
  `RUNNING / RESULT_PUBLISH`, never falsely `SUCCEEDED`.

P5-S8 does not publish or acknowledge the delivery. It also introduces no
WC, Project, LOCAL_SKILL, NSL execution, or WRITE identity.

## Completion Verification

- ExecutablePlan and every StepResult are revalidated against their v1.1
  contracts before synthesis.
- The StepResult set must exactly cover the plan's compiled E-key set with
  matching execution, plan, runtime step UUID, and logical S-key lineage.
- Required completion criteria select the output E-keys. Intermediate results
  never create AgentResult independently.
- The input result-set hash is calculated from ordered StepResult identity,
  status, contract, and semantic hash, using the shared canonical SHA-256
  utility.
- Required result status is reduced conservatively in this precedence:
  `FAILED`, `CANCELLED`, `BLOCKED`, otherwise `SUCCEEDED`.

## AgentResult Projection

- Result and delivery UUIDs are deterministic UUIDv5 identities derived from
  tenant, execution, and immutable input result-set hash. Restart therefore
  reconstructs the same identity.
- WorkIntent, AgentContext, AgentPlan, ExecutablePlan, completion criteria,
  output StepResults, artifacts, external references, and evidence remain
  references/hashes. Step `result_payload` and private prompt/response content
  are not copied into AgentResult.
- AgentResult provenance records the exact ExecutablePlan ID/hash and input
  result-set hash.
- P5 StepResult WRITE fields remain null and no NSL identity is synthesized.

## Atomic Persistence

- The existing P4 AgentResult repository now exposes a distinct P5 plan
  authority path while preserving its compatibility-step path unchanged.
- In the write transaction it locks AgentExecution and rechecks
  `RUNNING / RESULT_VERIFY`, latest ExecutablePlan identity, and the exact DB
  StepResult hash map.
- AgentResult insert, required PENDING delivery insert, and AgentExecution
  transition share one transaction.
- Same result identity/hash replays idempotently; changed plan/result authority
  fails closed.

## Verification

- Focused tests passed `73/73` across the legacy P4 repository, P5 completion
  verification, plan-level projection, failure precedence, idempotent replay,
  and protected-smoke contracts.
- `nex_ae_api.agent_results` and `nex_ae_api.plan_finalization` each reached
  `100%` statement and `100%` branch coverage in focused tests.
- Actual PostgreSQL smoke connected as `nex_ae_user@nex_ae_test`, verified all
  `38` migrations, and passed `27/27` checks over the complete S5→S7→S8
  journey.
- The smoke persisted two StepResults, one AgentResult, one required PENDING
  delivery, three RuntimeJobs/attempts, proved immutable replay and the ACK
  barrier, then left zero tenant residue.
- Remote providers were not required because the compatibility executor used
  a deterministic reference-only callback while all persistence was real.
- AE Slice Gate passed with `3474 passed`, `5` protected opt-in tests skipped;
  statement coverage `98.61%`, branch coverage `96.82%`.
- Contract validation passed `174` schemas, `236` examples, `204` negative
  examples, and `7` OpenAPI documents.

## Deferred

- P5-S9 owns final full regression, restart/dedup acceptance, zero-NSL audit,
  traceability closure, and P5 completion evidence.
- A later publication phase owns delivery jobs, preflight, ACK, reconciliation,
  and the final transition to `SUCCEEDED`.
