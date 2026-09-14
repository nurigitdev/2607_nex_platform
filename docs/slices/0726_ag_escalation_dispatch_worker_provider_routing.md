# Slice 0726: AG dispatch execution worker provider routing integration

## Intent

Connect the S72 dispatch execution worker to the S73 provider router while
keeping live network calls disabled.

## Implementation

- Added `execute_dispatch_with_provider_router(...)`.
- The router preserves `mock_first_only` behavior, routes notification/email/
  webhook rows to the mock notification adapter when `mock_http` is selected,
  and routes incident rows to the mock external incident adapter.
- Extended `run_dispatch_execution_worker_once(...)` with provider mode/config
  and mock status-code controls for deterministic worker regression tests.
- Updated worker item execution to use the router before transition planning and
  metadata persistence.
- Added regression coverage for mock-first skip behavior, live-channel routing,
  unsupported router channel guardrails, and full worker processing of
  notification plus external incident dispatch rows.

## Boundary

Slice 0726 does not enable live outbound network calls. Even `mock_http` and
guarded `live_http` routes still execute through local mock adapters until a
later protected live transport slice explicitly changes that boundary.

## Verification

```bash
PYTHONPATH=services/_shared:services/nex-ag ./.venv/bin/pytest tests/test_nex_ag_operator_review_dispatch_execution.py -q --cov=nex_ag.operator_review_dispatch_execution --cov-branch --cov-report=term-missing
```

Result: `33 passed`, `100%` statement coverage, `100%` branch coverage for
`nex_ag.operator_review_dispatch_execution`.
