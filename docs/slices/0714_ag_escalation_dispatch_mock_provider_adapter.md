# Slice 0714: AG escalation dispatch mock provider adapter

## Intent

Add the first S72 dispatch execution provider adapter while keeping execution
mock-only and free of outbound network delivery.

## Implementation

- Added `MockDispatchExecutionProvider`.
- Added `build_mock_dispatch_execution_provider(...)`.
- Added `execute_dispatch_with_mock_provider(...)`.
- Mock `MOCK` channel dispatches produce safe success/failure execution results
  using the Slice 0713 result contract.
- Non-`MOCK` live channels produce a safe `SKIPPED` result because live
  notification and external incident delivery remain deferred.

## Boundary

Slice 0714 still does not mutate dispatch rows, run worker batches, create
tables, or call external providers. It only proves provider adapter output shape
and redaction behavior.

## Verification

```bash
PYTHONPATH=services/_shared:services/nex-ag ./.venv/bin/pytest tests/test_nex_ag_operator_review_dispatch_execution.py -q --cov=nex_ag.operator_review_dispatch_execution --cov-branch --cov-report=term-missing
```
