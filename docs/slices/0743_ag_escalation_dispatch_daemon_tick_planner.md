# Slice 0743: AG dispatch execution daemon tick planner

## Intent

Add a non-mutating tick planner for the AG escalation dispatch execution daemon
so operators and later control routes can see what a bounded daemon tick would
process before any state transition is applied.

## Implementation

- Added `build_dispatch_execution_daemon_tick_plan`.
- Reused the existing dispatch worker candidate selector so the daemon plan and
  run-once worker select the same `PENDING`, `RETRY_WAIT`, and `FAILED`
  dispatch records.
- The plan reports candidate counts, status/channel distribution, safe candidate
  summaries, provider mode, dry-run state, and confirmation requirements.
- The planner never mutates dispatch records and does not require a new table.

## Verification

```bash
./.venv/bin/pytest tests/test_nex_ag_operator_review_dispatch_execution.py -q --cov=nex_ag.operator_review_dispatch_execution --cov-branch --cov-report=term-missing
```

Result: `43 passed`, `100%` statement coverage, `100%` branch coverage for
`nex_ag.operator_review_dispatch_execution`.
