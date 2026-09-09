# Slice 0613: AE worker result route persistence wiring

## Scope

Wire the protected AE operator-control execution worker route to optionally
persist a safe worker result record.

## Decision

- The default worker route behavior remains non-persistent.
- `persist_worker_result=true` is the only route-level write trigger.
- Worker result writes require both the AE execution store and the AE worker
  result store.
- The source execution state must already exist in the persisted execution
  state table before a result row can be written.
- The route continues returning the worker result contract unchanged; persisted
  rows are verified through the result store/read model instead.
- No new database table is added in this slice. The route uses the existing
  short `ae_op_exec_worker_results` table from Slice 0612.

## Implementation

- Added the default worker result store factory to the AE artifact route module.
- Extended artifact route registration to accept an injected worker result
  store for regression and future runtime composition.
- Added `persist_worker_result` parsing and guardrails to the protected worker
  route.
- Added regression coverage for default non-persistence, explicit result
  persistence, invalid persistence flags, unavailable stores, and orphan
  execution-state protection.

## Evidence

```bash
./.venv/bin/python -m py_compile services/nex-ae-api/nex_ae_api/artifacts.py services/nex-ae-api/nex_ae_api/artifact_retention_scheduler_daemon.py tests/test_nex_ae_artifact_retention_scheduler_daemon_operator_control_execution_worker_routes.py tests/test_nex_ae_artifacts.py
PYTHONPATH=services/_shared:services/nex-ae-api ./.venv/bin/pytest tests/test_nex_ae_artifact_retention_scheduler_daemon_operator_control_execution_worker_routes.py tests/test_nex_ae_artifact_retention_scheduler_daemon_operator_control_execution_worker_result_persistence.py -q
./scripts/quality/run_quality_gate.sh
```

Observed targeted regression:

```text
40 passed
```

Observed quality gate coverage:

```text
4338 passed
statement_coverage=98.58% threshold=95.00%
branch_coverage=95.72% threshold=85.00%
```

## Next

- Slice 0614 should prove this explicit route persistence path against the real
  `nex_ae_test` PostgreSQL database with protected smoke evidence.
