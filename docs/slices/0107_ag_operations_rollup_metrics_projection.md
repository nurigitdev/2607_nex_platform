# Slice 0107: AG Operations Rollup Metrics Projection

## Scope

Slice 0107 adds an AG read-only rollup endpoint for operator dashboards:

```text
GET /admin/v1/operations/rollups
```

The projection summarizes the jobs and operational events AG can currently
observe through memory or read-only PostgreSQL operations sources.

## Response Shape

The projection schema version is:

```text
ag_operations_rollup_metrics_projection.v1
```

Each service rollup contains:

- job totals, active/terminal counts, status counts, and job-type counts
- event totals, severity counts, and event-type counts
- job and event source status for that service

The top-level summary aggregates totals by service and counts source statuses
so AG can distinguish empty data from missing or unavailable sources.

## Query Contract

The route supports:

- `service_id`
- `since`
- `until`

`since` and `until` use the shared operations timestamp normalizer. Job rollups
use `updated_at` with the existing `created_at` fallback. Event rollups use
`created_at`.

Rollups are not paginated because the service set is fixed and small.

## Contract Artifacts

Positive example:

```text
contracts/examples/operations/ag_operations_rollup_metrics.mock_success.json
```

Negative example:

```text
contracts/tests/negative/operations/ag_operations_rollup_metrics.missing_rollups.json
```

The frozen operations family schema now includes
`ag_operations_rollup_metrics_projection.v1`.

## SQLite/PostgreSQL Strategy

The rollup builder stays above the persistence adapter layer. Regression tests
use in-memory sources, while PostgreSQL behavior continues to be covered by the
AG operations source registry and guarded smoke packs.

## Evidence

Targeted regression:

```bash
./.venv/bin/pytest tests/test_contract_validation.py tests/test_nex_ag_operations.py
```

Full quality gate:

```bash
scripts/quality/run_quality_gate.sh
```
