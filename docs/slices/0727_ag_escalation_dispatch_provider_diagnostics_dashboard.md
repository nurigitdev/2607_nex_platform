# Slice 0727: AG dispatch provider result diagnostics dashboard

## Intent

Surface safe provider diagnostics from dispatch execution results in AG
operations without exposing raw provider payloads or secrets.

## Implementation

- Extended dispatch execution result metadata with provider category, provider
  request hash, HTTP status code, and response body hash.
- Extended the AG operations dispatch execution projection with item-level
  provider diagnostics.
- Added execution summary rollups for provider category, provider profile, HTTP
  status code, and last error code.
- Updated the operations projection contract schema and mock dashboard example
  to make the new diagnostic summary fields canonical.
- Added regression coverage in dispatch execution and operations dashboard tests.

## Boundary

Slice 0727 only projects safe provider diagnostics. It does not store raw
provider request/response bodies, endpoint URLs, headers, service tokens,
authorization values, or idempotency keys.

## Verification

```bash
PYTHONPATH=services/_shared:services/nex-ag ./.venv/bin/pytest tests/test_nex_ag_operator_review_dispatch_execution.py tests/test_nex_ag_operations.py -q --cov=nex_ag.operator_review_dispatch_execution --cov=nex_ag.operations --cov-branch --cov-report=term-missing
```

Result: `206 passed`, `98%` combined coverage; dispatch execution remains
`100%` statement and branch coverage.

```bash
PYTHONPATH=services/_shared:services/nex-ag:services/nex-oa:services/nex-ae-api:services/nex-cx:services/nex-mo:providers/nex-compatible-provider:scripts/db:scripts/dev:scripts/smoke:scripts/quality ./.venv/bin/python scripts/quality/validate_contracts.py
```

Result: `contract_validation=pass schemas=77 examples=123 negative_examples=87 openapi=7`.
