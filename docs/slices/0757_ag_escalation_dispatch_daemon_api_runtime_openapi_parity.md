# Slice 0757: AG escalation dispatch daemon API runtime OpenAPI parity

## Intent

Keep the S76 dispatch daemon API implementation aligned with the published AG
OpenAPI contract by pinning runtime operation IDs and tags.

## Implementation

- Added explicit FastAPI `operation_id` values and `Operations` tags for:
  - `GET /admin/v1/operator-review/dispatch-daemon/tick-plan`
  - `POST /admin/v1/operator-review/dispatch-daemon/tick-plan`
  - `POST /admin/v1/operator-review/dispatch-daemon/tick-once`
- Added a regression test that compares runtime FastAPI OpenAPI output with the
  static `contracts/openapi/nex-ag.openapi.yaml` operation IDs and tags.
- No database migration or table changes are required.

## Verification

```bash
./.venv/bin/python -m py_compile services/nex-ag/nex_ag/operations.py tests/test_nex_ag_operations.py
```

Result: passed.

```bash
./.venv/bin/pytest tests/test_nex_ag_operations.py -k 'dispatch_daemon_runtime_openapi or dispatch_daemon_tick' -q
```

Result: `8 passed, 174 deselected`.
