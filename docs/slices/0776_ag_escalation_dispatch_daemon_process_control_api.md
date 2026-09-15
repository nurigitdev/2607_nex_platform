# Slice 0776: AG dispatch daemon protected process control API

## Intent

Expose a protected operator API for AG dispatch daemon process controls while
keeping subprocess mutation disabled and contract-only.

## Implementation

- Added process control request, admission, and projection contracts.
- Supported actions:
  - `status_probe`
  - `start_process`
  - `stop_process`
- `start_process` and `stop_process` require `confirm_process=True`.
- Confirmed controls return safe admission/projection data but do not start or
  stop a subprocess in this slice.
- Added protected route:
  `POST /admin/v1/operator-review/dispatch-daemon/process-controls`.
- Route responses reuse existing process metadata/runtime state and remain
  redaction-safe.
- No new database table is introduced.

## Verification

```bash
./.venv/bin/pytest tests/test_nex_ag_operator_review_dispatch_execution.py -q --cov=nex_ag.operator_review_dispatch_execution --cov-branch --cov-report=term-missing
```

Result: `68 passed in 2.84s`.

Coverage for `nex_ag.operator_review_dispatch_execution`: statement `100%`,
branch `100%`.

```bash
./.venv/bin/pytest tests/test_nex_ag_operations.py -q --cov=nex_ag.operations --cov-branch --cov-report=term-missing
```

Result: `193 passed, 1 warning in 10.83s`.

Coverage for `nex_ag.operations`: statement/branch aggregate `98%`.
