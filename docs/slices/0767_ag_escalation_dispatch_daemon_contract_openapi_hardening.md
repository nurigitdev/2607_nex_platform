# Slice 0767: AG dispatch daemon contract/OpenAPI hardening

## Objective

Lock the S77 dispatch daemon operations surface into OpenAPI and contract
examples so route drift is caught early.

## Scope

- Added the protected control-history route to `nex-ag` OpenAPI:
  `GET /admin/v1/operator-review/dispatch-daemon/controls`.
- Added OpenAPI components for safe dispatch daemon control history projection
  and control-history item payloads.
- Added the control-history projection version to the generic AG operations
  projection schema enum in OpenAPI.
- Extended the dispatch daemon route contract enum to include the controls
  history route.
- Added the Slice 0765 `daemon_controls` dashboard section to the dashboard
  mock example with safe redaction defaults.
- Hardened contract validation tests so the route, response schema, query
  parameters, history-action enum, and example section are checked.

## Regression

```bash
./.venv/bin/pytest tests/test_contract_validation.py -q --cov=validate_contracts --cov-branch --cov-report=term-missing
```

Result: `28 passed`; `validate_contracts.py` statement coverage `96%`.

```bash
./.venv/bin/python scripts/quality/validate_contracts.py
```

Result:
`contract_validation=pass schemas=77 examples=123 negative_examples=87 openapi=7`.

```bash
./.venv/bin/pytest --cov --cov-branch --cov-report=term
```

Result: `5113 passed, 1 warning in 303.43s`.

Coverage: statement `98.67%` (`65575/66457`), branch `96.04%`
(`15687/16334`).
