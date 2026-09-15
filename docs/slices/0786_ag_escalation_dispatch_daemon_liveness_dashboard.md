# Slice 0786: AG dispatch daemon liveness dashboard integration

## Objective

Surface AG operator review escalation dispatch daemon heartbeat/liveness state in
the unified AG operations dashboard.

## Scope

- Added `daemon_liveness` to the
  `operator_review_escalation_dispatches` dashboard section.
- Reused the Slice 0784 liveness read model so the protected liveness route and
  dashboard share the same heartbeat projection shape.
- Passed worker heartbeat stores through the protected dashboard route.
- Reported liveness source `UNAVAILABLE` states in top-level
  `degraded_sources`.
- Kept `NOT_CONFIGURED` liveness sources non-fatal for legacy/partial dashboard
  registry setups while still exposing the subsection source status.
- Updated the operations projection schema and mock dashboard example.
- Introduced no new table and no write mutation.

## Regression

```bash
./.venv/bin/pytest tests/test_nex_ag_operations.py -q -k "dashboard and (dispatch or route or degraded_sources)"
```

Result: `9 passed, 188 deselected, 1 warning in 2.46s`.

```bash
./.venv/bin/pytest tests/test_contract_validation.py -q
```

Result: `28 passed in 2.63s`.

```bash
./.venv/bin/pytest tests/test_nex_ag_operations.py -q --cov=nex_ag.operations --cov-branch --cov-report=term-missing
```

Result: `197 passed, 1 warning in 12.22s`.

Coverage for `nex_ag.operations`: statement/branch remained in the existing
high-coverage band.

```bash
./.venv/bin/pytest --cov --cov-branch --cov-report=term
```

Result: `5211 passed, 1 warning in 314.73s`.

Coverage totals: statement `98.69%` (`66722/67605` lines covered),
branch `96.08%` (`15913/16562` branches covered).
