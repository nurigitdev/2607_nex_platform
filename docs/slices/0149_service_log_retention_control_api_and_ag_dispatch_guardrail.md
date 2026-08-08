# Slice 0149: Service Log Retention Control API and AG Dispatch Guardrail

## Scope

Slice 0149 exposes the guarded service log retention purge capability through
service-local internal APIs and an AG dispatch boundary.

Implemented:

- `POST /internal/v1/service-logs/retention/purge`
- service claim authorization for service-local retention control
- shared app wiring for `nex-oa`, `nex-ag`, `nex-ae-api`, `nex-cx`, and `nex-mo`
- `HttpAgServiceLogRetentionClient`
- `POST /admin/v1/operations/logs/retention/{service_id}/purge`
- AG dispatch projection `ag_service_log_retention_dispatch.v1`
- AG audit event wrapping for retention dispatch success and failure

## Guardrails

The control path stays safe by default:

- service-local requests default to `dry_run=true`
- `dry_run=true` rejects `delete_enabled=true`
- service-local execute requests without `delete_enabled=true` return a
  `BLOCKED` `service_log_retention_execution.v1`
- AG execute-mode dispatch without `delete_enabled=true` is blocked before any
  service call is made
- execute-mode purges still obey `max_delete_count`

## Boundary

This Slice does not add OpenAPI documentation or scheduled retention workers.
OpenAPI contract freeze and smoke evidence are expected in the next Slice.

## Evidence

Targeted regression:

```bash
./.venv/bin/pytest tests/test_nex_runtime_service_logs.py tests/test_nex_ag_service_log_retention.py tests/test_nex_ag_operations.py
```

Quality gate:

```bash
scripts/quality/run_quality_gate.sh
```
