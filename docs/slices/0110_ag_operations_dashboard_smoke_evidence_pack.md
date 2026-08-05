# Slice 0110: AG Operations Dashboard Smoke Evidence Pack

## Scope

Slice 0110 adds a mock-first AG operations smoke pack:

```text
scripts/smoke/run_ag_operations_dashboard_smoke.py
```

The smoke validates the AG operations observability surface introduced across
Slices 0101 through 0109 without requiring PostgreSQL, DGX, or external
services.

## Covered Endpoints

The smoke calls these AG routes through `TestClient`:

- `GET /admin/v1/operations/sources`
- `GET /admin/v1/operations`
- `GET /admin/v1/operations/event-taxonomy`
- `GET /admin/v1/operations/events`
- `GET /admin/v1/operations/events/{event_id}`
- `GET /admin/v1/operations/jobs`
- `GET /admin/v1/operations/jobs/{service_id}/{job_id}`
- `GET /admin/v1/operations/traces/{trace_id}`
- `GET /admin/v1/operations/rollups`
- `GET /admin/v1/operations/dashboard`
- `GET /admin/v1/operations/issue-candidates`

## Evidence Shape

The smoke emits:

```text
ag_operations_dashboard_smoke.v1
```

Evidence includes endpoint count, projection versions, core counts, and boolean
checks for source readiness, unified job/event visibility, redaction, job
lifecycle timeline, trace timeline mixing, rollups, dashboard failure/active
signals, and issue candidates.

## Quality Gate

`scripts/quality/run_quality_gate.sh` now runs:

```bash
./.venv/bin/python scripts/smoke/run_ag_operations_dashboard_smoke.py --summary
```

The existing PostgreSQL operations smoke remains guarded by environment flags
and is unchanged.

## Evidence

Targeted regression:

```bash
./.venv/bin/pytest tests/test_smoke_helpers.py tests/test_nex_ag_operations.py
```

Expected summary line:

```text
ag_operations_dashboard_smoke=pass endpoints=11 jobs=2 events=1 issues=2
```

Full quality gate:

```bash
scripts/quality/run_quality_gate.sh
```
