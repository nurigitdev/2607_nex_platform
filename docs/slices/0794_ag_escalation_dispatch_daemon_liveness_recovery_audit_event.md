# Slice 0794: AG dispatch liveness recovery audit event

## Objective

Persist safe operational evidence whenever an operator views or is rejected
from the AG dispatch daemon liveness recovery-plan route.

## Scope

- Added liveness recovery audit event constants:
  - planned
  - rejected
  - failed
- Added safe audit detail builder:
  `build_operator_review_escalation_dispatch_daemon_liveness_recovery_audit_event_details`.
- Added emitter:
  `emit_operator_review_escalation_dispatch_daemon_liveness_recovery_audit_event`.
- Wired the protected recovery-plan route to emit into `service_operational_events`.
- Added `audit_event` route response summary.
- Kept the route read-only:
  - `mutation=false`
  - `subprocess_mutation_performed=false`
  - no new database table
  - raw request/provider payloads and sensitive values are excluded

## Deferred

- Slice 0795: operations dashboard recovery action integration.
- Slice 0796: acknowledgement/suppression policy.
- Slice 0797: PostgreSQL smoke evidence for recovery-plan audit events.
- Slice 0799: static OpenAPI/schema hardening.

## Regression

```bash
./.venv/bin/pytest tests/test_nex_ag_operations.py -q -k "liveness_recovery_audit or liveness_recovery_plan_route or liveness_recovery_plan"
```

Result: `5 passed, 198 deselected, 1 warning in 1.58s`.

```bash
./.venv/bin/pytest tests/test_nex_ag_operations.py -q
```

Result: `203 passed, 1 warning in 4.34s`.

```bash
./.venv/bin/pytest --cov --cov-branch --cov-report=term
```

Result: `5247 passed, 1 warning in 320.42s`.

Coverage totals: statement `98.70%` (`67288/68173`), branch `96.09%`
(`16041/16694`).
