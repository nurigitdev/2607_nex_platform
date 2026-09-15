# Slice 0782: AG dispatch daemon heartbeat contract/wire shape

## Objective

Define the AG operator review escalation dispatch daemon heartbeat contract
before emitting heartbeats from the executable daemon boundary.

## Scope

- Added
  `DISPATCH_EXECUTION_DAEMON_HEARTBEAT_CONTRACT_SCHEMA_VERSION`.
- Added stable heartbeat identity constants:
  - `service_id`: `nex-ag`
  - `worker_type`: `operator_review_dispatch_daemon`
- Added `build_dispatch_execution_daemon_heartbeat_contract`.
- Added `build_dispatch_execution_daemon_heartbeat`.
- Reused shared `worker_heartbeat.v1` validation, status values, stale threshold
  normalization, and redaction rules.
- Confirmed Slice 0782 introduces no database table and performs no heartbeat
  persistence mutation.

## Contract Notes

- Default disabled daemon metadata maps to a `STOPPED` heartbeat.
- Ready/running process metadata maps to an `IDLE` heartbeat unless a caller
  explicitly emits `BUSY` with an `active_job_id`.
- Degraded runtime state maps to an `ERROR` heartbeat.
- Sensitive extra metadata keys such as `api_key`, `token`, `password`, and
  `secret` are ignored by the daemon-specific heartbeat metadata builder.

## Regression

```bash
./.venv/bin/pytest tests/test_nex_ag_operator_review_dispatch_execution.py -q --cov=nex_ag.operator_review_dispatch_execution --cov-branch --cov-report=term-missing
```

Result: `72 passed in 3.01s`.

Coverage for `nex_ag.operator_review_dispatch_execution`: statement `100%`,
branch `100%`.

```bash
./.venv/bin/pytest --cov --cov-branch --cov-report=term
```

Result: `5205 passed, 1 warning in 336.01s`.

Coverage totals: statement `98.69%` (`66663/67546`), branch `96.08%`
(`15891/16540`).
