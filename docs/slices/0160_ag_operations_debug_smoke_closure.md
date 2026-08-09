# Slice 0160: AG Operations Debug Smoke Closure

## Scope

Slice 0160 closes the current AG operations/debugging pass by folding retention
history visibility into the mock-first AG operations dashboard smoke.

Implemented:

- seeded retention execution history in the AG dashboard smoke fixture
- `GET /admin/v1/operations/logs/retention/history` coverage in
  `run_ag_operations_dashboard_smoke.py`
- smoke checks for retention history projection status, filters, execution ID,
  total count, and deleted-count summary
- dashboard smoke evidence count for retention history

## Operator Debugging Coverage

The mock-first dashboard smoke now exercises these AG debugging surfaces:

- source readiness
- unified jobs/events view
- operational event list and detail
- structured service log list and detail
- service log query policy
- service log retention dry-run
- service log retention history
- job list/detail lifecycle
- worker runtime/detail correlation
- trace timeline
- rollups
- dashboard snapshot
- issue candidates

## Evidence

Targeted regression:

```bash
./.venv/bin/pytest tests/test_smoke_helpers.py -k "ag_operations_dashboard_smoke"
```

Dashboard smoke summary:

```bash
./.venv/bin/python scripts/smoke/run_ag_operations_dashboard_smoke.py --summary
```

Expected summary:

```text
ag_operations_dashboard_smoke=pass endpoints=18 jobs=2 workers=1 events=1 logs=1 history=1 issues=3
```
