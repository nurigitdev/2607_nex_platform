# Slice 0612: AE worker result persistence schema/store

## Scope

Add the AE-owned schema and SQLite-regressed store foundation for safe
operator-control execution worker result persistence.

## Decision

- The result table is `ae_op_exec_worker_results` and stays at 25 characters.
- Index names use the short `idx_ae_op_worker_results_*` prefix.
- The stored payload is a safe summary record, not the full worker result.
- The result record stores source hashes for the worker command, transition
  plan, supervisor result list, and full worker result.
- Route-level writes still remain opt-in and are deferred to the next wiring
  slice.
- AG remains read/projection-only and must not write AE result rows directly.

## Implementation

- Added `0612_ae_worker_result_persistence` migration for
  `ae_op_exec_worker_results`.
- Added
  `SqlAlchemyArtifactRetentionSchedulerDaemonOperatorControlExecutionWorkerResultStore`.
- Added worker result safe-summary record builder, validator, summary helper,
  SQLite upsert/select/delete helpers, and filter normalization.
- Added regression coverage for safe projection, round-trip persistence,
  failed-result filtering, invalid payloads, DB error mapping, and migration
  table/index naming.

## Evidence

```bash
./.venv/bin/python -m py_compile services/nex-ae-api/nex_ae_api/artifact_retention_scheduler_daemon.py tests/test_nex_ae_artifact_retention_scheduler_daemon_operator_control_execution_worker_result_persistence.py
PYTHONPATH=services/_shared:services/nex-ae-api ./.venv/bin/pytest tests/test_nex_ae_artifact_retention_scheduler_daemon_operator_control_execution_worker_result_persistence.py -q
./scripts/quality/run_quality_gate.sh
```

Observed targeted regression:

```text
tests/test_nex_ae_artifact_retention_scheduler_daemon_operator_control_execution_worker_result_persistence.py: 33 passed
```

Observed quality gate coverage:

```text
4335 passed
statement_coverage=98.57% threshold=95.00%
branch_coverage=95.72% threshold=85.00%
```

## Next

- Slice 0613 should wire the protected AE worker route so
  `persist_worker_result=true` stores one safe result row while default route
  behavior remains non-persistent.
