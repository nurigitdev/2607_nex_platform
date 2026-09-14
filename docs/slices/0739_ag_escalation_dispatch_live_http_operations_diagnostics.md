# Slice 0739: AG dispatch live HTTP operations diagnostics

## Intent

Expose safer operational diagnostics for S74 live HTTP dispatches in the AG
operations dashboard.

## Implementation

- Persisted `attempt_count` into dispatch execution result metadata.
- Added execution summary fields for:
  - `by_provider_mode`
  - `response_body_hash_count`
  - `attempt_count_total`
  - `max_attempt_count`
- Updated the AG operations projection schema for the new summary fields.
- Kept raw endpoint URLs, authorization headers, idempotency keys, and raw
  provider payloads out of operations projection evidence.

## Verification

```bash
./.venv/bin/pytest tests/test_nex_ag_operator_review_dispatch_execution.py -q --cov=nex_ag.operator_review_dispatch_execution --cov-branch --cov-report=term-missing
```

Result: `38 passed`, `100%` statement coverage, `100%` branch coverage for
`nex_ag.operator_review_dispatch_execution`.

```bash
./.venv/bin/pytest tests/test_nex_ag_operations.py -q --cov=nex_ag.operations --cov-branch --cov-report=term-missing
```

Result: `173 passed`, `98%` statement/branch coverage for the AG operations
module test run.
