# P6-S0 AE Runtime Worker Foundation

**Status:** COMPLETE

## Scope

P6-S0 adds the dedicated AE Agent Runtime worker lifecycle without changing the
existing RuntimeJob authority or prematurely implementing the P6-S1 tenant
dispatcher.

## Source Review Decision

The existing source already separates the required responsibilities:

- `runtime_jobs.py` owns the AE RuntimeJob lease and attempt ledger;
- `multi_step_engine.py` owns durable plan/step scheduling;
- `step_executors.py` owns claimed-step execution; and
- shared `nex_runtime.worker_heartbeats` owns the common heartbeat store.

No broad `agent_runtime/` package move and no second JobQueue were justified.
P6-S0 therefore adds one focused `agent_runtime_worker.py` process boundary and
uses injected assignment and handler ports. P6-S1 will supply the DB-protected
dispatcher assignment source.

## Implementation

- Frozen the source-backed worker profile fields and semantic profile hash.
- Required `LOCAL_SKILL`, `NSL_V01_PROCESS_ISOLATED`, `SNAPSHOT_REQUIRED` and
  process isolation in the default P6 profile.
- Added fail-closed startup validation for missing executor/backend
  implementations.
- Added readiness projection over persisted worker heartbeats.
- Added bounded polling, active-claim accounting, drain, shutdown and
  SIGINT/SIGTERM adapters.
- Kept unexpected handler failure lease-safe: the worker records failure but
  does not invent RuntimeJob settlement outside the existing queue authority.
- Added restart-safe bounded execution with no process-local pending-work SoR.
- Added an executable `python -m nex_ae_api.agent_runtime_worker --check`
  entrypoint. P6-S1 now composes the dispatcher source; process execution stays
  fail-closed until P6-S4 provides the `LOCAL_SKILL` handler.

## PostgreSQL Acceptance

The protected smoke applied the current `nex-ae-api` migration inventory to
the actual `nex_ae_test` database and exercised:

```text
AgentExecution fixture
→ RuntimeJob enqueue
→ lease claim + immutable attempt
→ worker BUSY heartbeat
→ RuntimeJob completion
→ STOPPING/STOPPED heartbeat
→ same-worker restart
→ no duplicate claim
→ cleanup
```

Result:

```text
p6_s0_postgres=pass
actual_postgres=true
checks=11/11
jobs=1
attempts=1
heartbeats=1
remaining=0
```

This is real PostgreSQL evidence, not a skipped or SQLite path.

## Verification

```text
focused P6-S0 tests: 30 passed
core worker statement/branch coverage: 99%
existing RuntimeJob/step-worker/heartbeat regression pack: 96 passed
AE Slice Gate: 3499 passed, 5 protected PostgreSQL tests skipped by opt-in guards
AE statement coverage: 98.62%
AE branch coverage: 96.85%
contract validation: PASS (174 schemas, 236 examples, 204 negative examples, 7 OpenAPI)
ruff: PASS
py_compile: PASS
```

The five skipped tests are pre-existing environment-protected suites. The
P6-S0 protected PostgreSQL runner was separately enabled and passed against the
actual `nex_ae_test` database as recorded above.

## Closed by P6-S1

- DB-protected dispatcher leadership;
- runnable tenant discovery;
- tenant fairness and bounded rounds;
- capability-aware candidate filtering joined to ExecutableStep;
- claim eligibility and lease CAS in one transaction;
- backpressure and malformed-job reconciliation.

No static production tenant selector was introduced as a shortcut. See
`p6_s1_db_protected_tenant_dispatcher.md` for implementation and PostgreSQL
evidence.
