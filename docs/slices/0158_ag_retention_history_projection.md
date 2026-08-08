# Slice 0158: AG Retention History Projection

## Scope

Slice 0158 lets NeX-AG read service-local retention execution history across
configured service log sources.

Implemented:

- `ag_service_log_retention_history_projection.v1`
- `GET /admin/v1/operations/logs/retention/history`
- filters for service, mode, execution status, trace, request, idempotency key,
  time window, sort, cursor, and limit
- source status reporting for ready, not configured, and unavailable services
- AG projection contract coverage for retention history

## Boundary

Retention execution history remains service-owned. AG builds a read-only
projection from the configured operations source registry or injected stores; it
does not write another service's history records.

The projection intentionally embeds the service-local
`service_log_retention_history_entry.v1` records so operators can inspect the
original retention execution evidence without leaving the AG operations surface.

## Evidence

Targeted regression:

```bash
./.venv/bin/pytest tests/test_nex_ag_operations.py -k "retention_history or retention_dry_run or retention_route"
```

Contract validation and AG regression:

```bash
./.venv/bin/python scripts/quality/validate_contracts.py
./.venv/bin/pytest tests/test_nex_ag_operations.py
```
