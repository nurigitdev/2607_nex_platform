# Slice 0785: AG dispatch daemon protected liveness route

## Objective

Expose the AG operator review escalation dispatch daemon liveness read model
through a protected operations API route.

## Scope

- Added protected `GET /admin/v1/operator-review/dispatch-daemon/liveness`.
- Added runtime operation id:
  `getAgOperatorReviewDispatchDaemonLiveness`.
- Added route response handling through the existing AG problem response path.
- Added `worker_id` and `stale_after_seconds` query parameters.
- Updated the static `nex-ag` OpenAPI contract.
- Updated runtime/static OpenAPI parity tests.
- Introduced no new table and no write mutation.

## Regression

```bash
./.venv/bin/pytest tests/test_nex_ag_operations.py -q -k "dispatch_daemon_liveness or runtime_openapi"
```

Result: `5 passed, 192 deselected, 1 warning in 1.16s`.

```bash
./.venv/bin/pytest tests/test_contract_validation.py -q
```

Result: `28 passed in 4.62s`.

```bash
./.venv/bin/pytest tests/test_nex_ag_operations.py -q --cov=nex_ag.operations --cov-branch --cov-report=term-missing
```

Result: `197 passed, 1 warning in 13.04s`.

Coverage for `nex_ag.operations`: statement/branch remained in the existing
high-coverage band.

```bash
./.venv/bin/pytest --cov --cov-branch --cov-report=term
```

Result: `5211 passed, 1 warning in 309.26s`.

Coverage totals: statement `98.69%` (`66717/67600` lines covered),
branch `96.08%` (`15911/16560` branches covered).
