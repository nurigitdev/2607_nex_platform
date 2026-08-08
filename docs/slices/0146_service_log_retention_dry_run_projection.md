# Slice 0146: Service Log Retention Dry-Run Projection

## Scope

Slice 0146 adds a read-only AG projection that estimates structured service log
retention candidates without deleting rows.

Implemented:

- `ag_service_log_retention_dry_run_projection.v1`
- `GET /admin/v1/operations/logs/retention/dry-run`
- service-local source status reporting for retention scans
- safe retention candidate summaries that omit log `message` and `attributes`
- contract schema, OpenAPI, example, and mock smoke coverage

## Projection

The dry-run endpoint accepts:

- `service_id`: optional service filter
- `retention_days`: optional retention window, clamped to the active policy
  bounds of `7` to `365` days
- `limit`: optional page size, clamped to the service log limit bounds

The response includes the active service log policy, retention cutoff,
source statuses, pagination, and candidate summaries. Candidate records include
only identifiers, timestamps, severity, logger, subject reference, age in days,
and redacted attribute key names.

## Boundary

This Slice does not delete service logs, schedule retention jobs, compact tables,
or archive rows to object storage. The `dry_run.delete_enabled` field is always
`false`, and purge execution remains `not_implemented`.

## Evidence

Targeted regression:

```bash
./.venv/bin/pytest tests/test_nex_ag_operations.py tests/test_smoke_helpers.py tests/test_contract_validation.py
```

Operations smoke:

```bash
./.venv/bin/python scripts/smoke/run_ag_operations_dashboard_smoke.py --summary
```
