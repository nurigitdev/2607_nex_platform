# Slice 0150: Service Log Retention OpenAPI and Smoke Evidence

## Scope

Slice 0150 freezes the service log retention control surface in OpenAPI and adds
default mock-first smoke evidence.

Implemented:

- CX representative service-local OpenAPI path:
  `POST /internal/v1/service-logs/retention/purge`
- AG operator-facing OpenAPI path:
  `POST /admin/v1/operations/logs/retention/{service_id}/purge`
- AG retention request/dispatch OpenAPI schemas
- AG operations projection schema version vocabulary update for
  `ag_service_log_retention_dispatch.v1`
- `run_ag_service_log_retention_smoke.py`
- default quality gate integration for the new smoke

## Smoke Flow

The smoke runs in-process with FastAPI `TestClient` instances:

1. CX service-local retention dry-run through AG dispatch.
2. unsafe execute-mode request blocked by AG before a service call.
3. guarded execute-mode request with `delete_enabled=true`.
4. audit event checks for success, failure, and success.
5. store-state checks that only one old log was deleted and fresh logs remain.

## Evidence

Targeted regression:

```bash
./.venv/bin/pytest tests/test_contract_validation.py tests/test_smoke_helpers.py
```

Smoke:

```bash
./.venv/bin/python scripts/smoke/run_ag_service_log_retention_smoke.py --summary
```

Quality gate:

```bash
scripts/quality/run_quality_gate.sh
```
