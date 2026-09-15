# Slice 0783: AG dispatch daemon heartbeat emission

## Objective

Emit AG operator review escalation dispatch daemon heartbeats from the executable
daemon boundary while preserving the existing no-emitter behavior.

## Scope

- Added optional `heartbeat_emitter` support to
  `execute_dispatch_execution_daemon_cli`.
- Kept `build_dispatch_execution_daemon_cli_plan` side-effect free.
- Emitted `STARTING -> BUSY -> STOPPED` for successful `run_once` execution.
- Emitted `STARTING -> BUSY -> ERROR` when the bounded loop produces a degraded
  runtime state.
- Added `heartbeat_events` summaries to the CLI result.
- Kept plan-only execution read-only with `heartbeat_events: []`.
- Reused the Slice 0782 daemon heartbeat wire shape for safe metadata.

## Regression

```bash
./.venv/bin/pytest tests/test_nex_ag_operator_review_dispatch_daemon_cli.py -q --cov=nex_ag.operator_review_dispatch_daemon --cov-branch --cov-report=term-missing
```

Result: `10 passed in 1.89s`.

Coverage for `nex_ag.operator_review_dispatch_daemon`: statement `100%`,
branch `100%`.

```bash
./.venv/bin/pytest --cov --cov-branch --cov-report=term
```

Result: `5207 passed, 1 warning in 334.47s`.

Coverage totals: statement `98.69%` (`66672/67555`), branch `96.08%`
(`15895/16544`).
