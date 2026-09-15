# Slice 0774: AG dispatch daemon executable CLI

## Intent

Add a thin executable facade for the AG dispatch daemon that can produce a safe
plan or execute one bounded loop without introducing a background service,
subprocess supervisor, or new database table.

## Implementation

- Added `nex_ag.operator_review_dispatch_daemon`.
- Added CLI plan/result contracts:
  - `ag_operator_review_escalation_dispatch_execution_daemon_cli_plan.v1`
  - `ag_operator_review_escalation_dispatch_execution_daemon_cli_result.v1`
- CLI default mode is plan-only.
- `--run-once` delegates to `run_dispatch_execution_daemon_bounded_loop`.
- The facade reuses process metadata and runtime state from Slice 0773.
- The default execution service is an empty in-memory service, so local smoke
  can verify command shape without requiring a database.
- Real test DB execution remains reserved for Slice 0778.

## Verification

```bash
./.venv/bin/pytest tests/test_nex_ag_operator_review_dispatch_daemon_cli.py -q --cov=nex_ag.operator_review_dispatch_daemon --cov-branch --cov-report=term-missing
```

Result: `7 passed in 0.98s`.

Coverage for `nex_ag.operator_review_dispatch_daemon`: statement `100%`,
branch `100%`.
