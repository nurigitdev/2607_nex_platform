# Slice 0792: AG dispatch liveness recovery action-plan contract

## Objective

Add the S80 liveness recovery action-plan contract without opening a new route,
creating a new database table, emitting audit events, or performing daemon
subprocess mutation.

## Scope

- Added
  `AG_OPERATOR_REVIEW_DISPATCH_DAEMON_LIVENESS_RECOVERY_PLAN_SCHEMA_VERSION`.
- Added
  `build_operator_review_escalation_dispatch_daemon_liveness_recovery_plan`.
- Kept recovery planning as a pure read model derived from the S79 liveness
  projection.
- Mapped liveness states to guarded operator actions:
  - `FRESH`: no action.
  - `STALE`: `inspect_stale_dispatch_daemon_heartbeat`.
  - `MISSING`: `start_or_inspect_dispatch_daemon_process`.
  - `SOURCE_NOT_CONFIGURED`: `configure_dispatch_daemon_heartbeat_store`.
  - `SOURCE_UNAVAILABLE`: `inspect_dispatch_daemon_heartbeat_store`.
  - unknown statuses: inspect the liveness projection contract.
- Confirmed the contract references the existing protected process-control
  route but keeps `mutation=false`, `dry_run_only=true`, and
  `subprocess_mutation_performed=false`.

## Deferred

- Slice 0793: protected recovery-plan route.
- Slice 0794: recovery audit event emission.
- Slice 0795: dashboard recovery integration.
- Slice 0796: acknowledgement/suppression policy.

## Regression

```bash
./.venv/bin/pytest tests/test_nex_ag_operations.py -q -k "liveness_recovery_plan or liveness_projection" --cov=nex_ag.operations --cov-branch --cov-report=term-missing
```

Result: `6 passed, 195 deselected, 1 warning in 2.45s`.

Note: this targeted run intentionally exercises only the liveness and recovery
plan paths inside the large AG operations module; full-suite coverage is
recorded after the complete Slice 0792 regression.

```bash
./.venv/bin/pytest tests/test_nex_ag_operations.py -q
```

Result: `201 passed, 1 warning in 2.12s`.

```bash
./.venv/bin/pytest --cov --cov-branch --cov-report=term
```

Result: `5245 passed, 1 warning in 299.70s`.

Coverage totals: statement `98.70%` (`67238/68123`), branch `96.09%`
(`16033/16686`).
