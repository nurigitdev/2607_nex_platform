# Slice 0108: AG Operations Dashboard Snapshot Projection

## Scope

Slice 0108 adds an AG dashboard snapshot endpoint:

```text
GET /admin/v1/operations/dashboard
```

The endpoint gives operators a first-screen view by composing existing
operations source readiness, rollup metrics, recent failure candidates, active
jobs, and degraded source signals.

## Response Shape

The projection schema version is:

```text
ag_operations_dashboard_snapshot_projection.v1
```

The dashboard snapshot includes:

- operation source readiness rows and summary
- per-service job/event rollups and aggregate rollup summary
- recent failed jobs and `ERROR`/`CRITICAL` operational events
- active `QUEUED`/`RUNNING` jobs
- degraded readiness, job-source, and event-source entries

## Query Contract

The route supports:

- `service_id`
- `since`
- `until`
- `recent_limit`

`recent_limit` is clamped to `1..20`. Job timestamps use the existing
operations `updated_at` with `created_at` fallback; event timestamps use
`created_at`.

## Contract Artifacts

Positive example:

```text
contracts/examples/operations/ag_operations_dashboard_snapshot.mock_success.json
```

Negative example:

```text
contracts/tests/negative/operations/ag_operations_dashboard_snapshot.missing_recent_failures.json
```

The operations family schema now includes
`ag_operations_dashboard_snapshot_projection.v1`.

## SQLite/PostgreSQL Strategy

The dashboard remains a read-only projection above the operations source
registry. Regression tests use in-memory sources, while PostgreSQL behavior is
covered by existing guarded AG operations source smoke packs.

## Evidence

Targeted regression:

```bash
./.venv/bin/pytest tests/test_contract_validation.py tests/test_nex_ag_operations.py tests/test_nex_runtime_app.py
```

Full quality gate:

```bash
scripts/quality/run_quality_gate.sh
```
