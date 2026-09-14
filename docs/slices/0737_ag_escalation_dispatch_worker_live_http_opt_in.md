# Slice 0737: AG dispatch worker live HTTP opt-in

## Intent

Wire live HTTP transport into the AG dispatch router and worker only as an
explicit opt-in path.

## Implementation

- `execute_dispatch_with_provider_router` now routes `provider_mode=live_http`
  through `execute_dispatch_with_live_http_transport`.
- `run_dispatch_execution_worker_once` accepts an injected `live_http_transport`
  and passes it to worker item execution.
- The mock-first default and `mock_http` provider behavior remain unchanged.
- Missing live transport still fails before any implicit network behavior.

## Verification

```bash
./.venv/bin/pytest tests/test_nex_ag_operator_review_dispatch_execution.py -q --cov=nex_ag.operator_review_dispatch_execution --cov-branch --cov-report=term-missing
```

Result: `38 passed`, `100%` statement coverage, `100%` branch coverage for
`nex_ag.operator_review_dispatch_execution`.
