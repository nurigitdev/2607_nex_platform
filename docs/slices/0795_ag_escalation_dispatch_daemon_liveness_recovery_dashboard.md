# Slice 0795: AG dispatch liveness recovery dashboard

## Objective

Surface dispatch daemon liveness recovery guidance inside the AG operations
dashboard without adding a new persistence table or mutating the daemon process.

## Scope

- Added dashboard section schema version:
  `ag_operator_review_escalation_dispatch_daemon_liveness_recovery_dashboard_section.v1`.
- Added `daemon_recovery` to
  `operator_review_escalation_dispatches`.
- Derived dashboard recovery guidance from the existing `daemon_liveness`
  projection and Slice 0792 recovery-plan contract.
- Kept source status contract conservative:
  - source status remains `READY` when the recovery section is derived,
  - actual operator attention is represented by `recovery_plan_status`,
  - bad projection input degrades only the recovery section.
- Updated AG operations projection schema and mock success example.
- Added regression coverage for:
  - fresh heartbeat `NO_ACTION`,
  - missing heartbeat `ACTION_RECOMMENDED`,
  - unavailable heartbeat source `SOURCE_ATTENTION`,
  - malformed liveness projection degraded fallback.

## Deferred

- Slice 0796: acknowledgement/suppression policy.
- Slice 0797: PostgreSQL smoke evidence for recovery-plan audit/dashboard state.
- Slice 0799: static OpenAPI/schema hardening for recovery routes.

## Regression

```bash
./.venv/bin/pytest tests/test_nex_ag_operations.py -q -k "dashboard_dispatch_daemon_liveness_recovery or dashboard_snapshot_includes_escalation_dispatches or dashboard_escalation_dispatches_handles_filters_and_errors or liveness_recovery_plan"
```

Result: `7 passed, 197 deselected, 1 warning in 1.62s`.

```bash
./.venv/bin/pytest tests/test_contract_validation.py -q
```

Result: `28 passed in 3.53s`.

```bash
./.venv/bin/pytest tests/test_nex_ag_operations.py -q
```

Result: `204 passed, 1 warning in 5.57s`.

```bash
./.venv/bin/pytest --cov --cov-branch --cov-report=term
```

Result: `5248 passed, 1 warning in 323.14s`.

Coverage totals: statement `98.70%` (`67307/68192`), branch `96.09%`
(`16045/16698`).
