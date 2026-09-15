# Slice 0799: AG dispatch liveness recovery OpenAPI hardening

## Objective

Close the S80 static contract gap for the dispatch daemon liveness recovery-plan
route so runtime OpenAPI and the checked-in `nex-ag` OpenAPI contract cannot
drift.

## Scope

- Added the static OpenAPI path:
  `GET /admin/v1/operator-review/dispatch-daemon/liveness/recovery-plan`.
- Added `AgOperatorReviewDispatchDaemonLivenessRecoveryPlanProjection` with
  the recovery-plan envelope, route guards, summary flags, runbook action
  shape, acknowledgement/suppression policy envelope, and redaction guardrails.
- Extended `AgOperatorReviewDispatchDaemonRoute` and `AgOperationsProjection`
  schema enums to include the recovery-plan route/version.
- Hardened contract validation tests for:
  - operation id and query parameters,
  - 200 response schema reference,
  - recovery route/process-control constants,
  - recovery summary/guardrail invariants,
  - dashboard example recovery path and redaction defaults.
- Extended the AG runtime/static OpenAPI drift test to include the recovery-plan
  route.

## Deferred

- Slice 0800: S80 recovery foundation closure checkpoint.
- Future operator action-state slice: persist acknowledgement/suppression state
  after operator identity and reason-code policy are finalized.

## Regression

```bash
./.venv/bin/python scripts/quality/validate_contracts.py
```

Result:
`contract_validation=pass schemas=77 examples=123 negative_examples=87 openapi=7`.

```bash
./.venv/bin/pytest tests/test_contract_validation.py -q
```

Result: `28 passed in 1.66s`.

```bash
./.venv/bin/pytest tests/test_nex_ag_operations.py -q -k "runtime_openapi_matches_contract or liveness_recovery_plan_route_is_protected"
```

Result: `2 passed, 203 deselected, 1 warning in 1.34s`.

```bash
./.venv/bin/pytest --cov --cov-branch --cov-report=term
```

Result: `5268 passed, 1 warning in 306.70s`.

Coverage totals from `/tmp/nex_platform_0799_coverage.json`:

- statement coverage: `98.71290303772375%` (`67721/68604`)
- branch coverage: `96.12361557699178%` (`16143/16794`)
