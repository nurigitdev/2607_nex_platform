# Slice 0144: Service Log Rollup Metrics Projection

## Scope

Slice 0144 adds structured service log metrics to AG operations rollup
projections and dashboard rollup snapshots.

Implemented:

- `logs` section in each `ag_operations_rollup_metrics_projection.v1` rollup
- aggregate `summary.logs`
- top-level `log_source_statuses`
- `source_status.logs` on each service rollup
- contract schema/example updates
- operations dashboard smoke assertion for log rollup visibility

## Metrics

Each service rollup now includes:

- `total`
- `by_severity`
- `by_logger_name`
- `redacted_attribute_count`

The projection summary also aggregates total logs, severity counts, per-service
counts, and total redacted attribute keys across selected services.

## Source Status

Log source handling stays aligned with Slices 0142-0143:

- `READY` log sources contribute log metrics.
- `UNAVAILABLE` log sources degrade the rollup projection.
- `NOT_CONFIGURED` log sources are reported in `log_source_statuses`, but do not
  degrade rollups while structured service log adoption remains incremental.

## Evidence

Targeted regression:

```bash
./.venv/bin/pytest tests/test_nex_ag_operations.py tests/test_smoke_helpers.py tests/test_contract_validation.py
```

Operations smoke:

```bash
./.venv/bin/python scripts/smoke/run_ag_operations_dashboard_smoke.py --summary
```

