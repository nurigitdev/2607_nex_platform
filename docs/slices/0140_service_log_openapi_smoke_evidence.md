# Slice 0140: Service Log OpenAPI And Smoke Evidence

## Scope

Slice 0140 freezes the AG structured service log read API in OpenAPI and folds
the log list/detail endpoints into the default mock-first operations smoke.

Implemented:

- `GET /admin/v1/operations/logs` in `nex-ag.openapi.yaml`
- `GET /admin/v1/operations/logs/{log_id}` in `nex-ag.openapi.yaml`
- `ServiceLogSeverity` OpenAPI component
- `ag_service_log_projection.v1` and `ag_service_log_detail_projection.v1`
  projection enum entries
- mock service log fixtures in `run_ag_operations_dashboard_smoke.py`
- smoke checks for log visibility and redaction preservation

## Evidence

Targeted regression:

```bash
./.venv/bin/pytest tests/test_smoke_helpers.py tests/test_contract_validation.py
./.venv/bin/python scripts/quality/validate_contracts.py contracts
./.venv/bin/python scripts/smoke/run_ag_operations_dashboard_smoke.py --summary
```

Expected smoke summary:

```text
ag_operations_dashboard_smoke=pass endpoints=15 jobs=2 workers=1 events=1 logs=1 issues=3
```
