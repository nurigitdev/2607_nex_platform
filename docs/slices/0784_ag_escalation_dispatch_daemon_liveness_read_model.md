# Slice 0784: AG dispatch daemon liveness read-model foundation

## Objective

Add an AG operator review escalation dispatch daemon liveness read model backed
by the shared `service_worker_heartbeats` source.

## Scope

- Added
  `AG_OPERATOR_REVIEW_DISPATCH_DAEMON_LIVENESS_PROJECTION_SCHEMA_VERSION`.
- Added `build_operator_review_escalation_dispatch_daemon_liveness_projection`.
- Reads the stable daemon heartbeat identity:
  - `service_id`: `nex-ag`
  - `worker_id`: `ag-dispatch-execution-daemon`
  - `worker_type`: `operator_review_dispatch_daemon`
- Summarizes liveness as:
  - `FRESH`
  - `STALE`
  - `MISSING`
  - `SOURCE_NOT_CONFIGURED`
  - `SOURCE_UNAVAILABLE`
- Keeps source health separate from daemon liveness:
  - source unavailable/not configured makes the projection `DEGRADED`,
  - a missing heartbeat remains a ready read model with `liveness_status:
    MISSING`.
- Introduces no new table.

## Regression

```bash
./.venv/bin/pytest tests/test_nex_ag_operations.py -q -k "dispatch_daemon_liveness"
```

Result: `3 passed, 193 deselected, 1 warning in 1.57s`.

```bash
./.venv/bin/pytest tests/test_nex_ag_operations.py -q --cov=nex_ag.operations --cov-branch --cov-report=term-missing
```

Result: `196 passed, 1 warning in 9.99s`.

Coverage for `nex_ag.operations`: statement/branch remained in the existing
high-coverage band.

```bash
./.venv/bin/pytest --cov --cov-branch --cov-report=term
```

Result: `5210 passed, 1 warning in 333.39s`.

Coverage totals: statement `98.69%` (`66706/67589`), branch `96.08%`
(`15909/16558`).
