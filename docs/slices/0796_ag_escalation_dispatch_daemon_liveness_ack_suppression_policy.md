# Slice 0796: AG dispatch liveness acknowledgement/suppression policy

## Objective

Define the read-only acknowledgement/suppression policy shape for dispatch daemon
liveness recovery signals so AG can expose operator actions without adding
persistence or mutating the daemon process in this slice.

## Scope

- Added policy schema version:
  `ag_operator_review_escalation_dispatch_daemon_liveness_ack_suppression_policy.v1`.
- Added `build_operator_review_escalation_dispatch_daemon_liveness_ack_suppression_policy`.
- Embedded the policy into the Slice 0792 liveness recovery-plan contract.
- Surfaced the policy through the Slice 0795 `daemon_recovery` dashboard section.
- Added issue-candidate signal summaries for acknowledgement/suppression policy
  metadata.
- Updated AG operations projection schema and mock success example.
- Kept policy state explicitly non-persistent:
  - no new tables required,
  - no current projection suppression,
  - future persistence target remains `operator_review_action_state`.

## Deferred

- Slice 0797: PostgreSQL smoke evidence for recovery-plan audit/dashboard state.
- Slice 0798: operator acknowledgement/suppression state persistence decision.
- Slice 0799: static OpenAPI/schema hardening for recovery routes.

## Regression

```bash
./.venv/bin/pytest tests/test_nex_ag_operations.py -q -k "ack_suppression or liveness_recovery_plan or dashboard_dispatch_daemon_liveness_recovery or dispatch_daemon_liveness"
```

Result: `12 passed, 193 deselected, 1 warning in 1.55s`.

```bash
./.venv/bin/pytest tests/test_contract_validation.py -q
```

Result: `28 passed in 3.98s`.

```bash
./.venv/bin/pytest tests/test_nex_ag_operations.py -q
```

Result: `205 passed, 1 warning in 6.12s`.

```bash
./.venv/bin/pytest --cov --cov-branch --cov-report=term
```

Result: `5249 passed, 1 warning in 321.28s`.

Coverage totals: statement `98.71%` (`67344/68227`), branch `96.11%`
(`16065/16716`).
