# Slice 0713: AG escalation dispatch execution provider/result contract

## Intent

Freeze the first S72 execution provider catalog and safe execution-result
contract before introducing worker adapters or batch execution.

## Implementation

- Added `nex_ag.operator_review_dispatch_execution`.
- Defined a mock-first provider catalog with `mock-default` and `mock-failure`
  profiles.
- Added `ag_operator_review_escalation_dispatch_execution_result.v1` runtime
  result shape.
- Added redaction guards for raw provider payloads, notification payloads,
  external incident payloads, secrets, database URLs, tokens, storage paths, raw
  comments, raw prompt/source text, and raw idempotency keys.

## Boundary

Slice 0713 does not execute providers, mutate dispatch rows, or add database
tables. It only defines the safe profile/result contract that later S72 slices
will use.

## Verification

```bash
PYTHONPATH=services/_shared:services/nex-ag ./.venv/bin/pytest tests/test_nex_ag_operator_review_dispatch_execution.py -q --cov=nex_ag.operator_review_dispatch_execution --cov-branch --cov-report=term-missing
```
