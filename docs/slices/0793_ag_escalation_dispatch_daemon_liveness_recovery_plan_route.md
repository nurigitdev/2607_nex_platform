# Slice 0793: AG dispatch liveness recovery-plan route

## Objective

Expose the S80 liveness recovery action-plan contract through a protected,
read-only AG operations route.

## Scope

- Added protected route:
  `GET /admin/v1/operator-review/dispatch-daemon/liveness/recovery-plan`.
- Added `_dispatch_daemon_liveness_recovery_plan_route_response`.
- Reused the S79 liveness projection and Slice 0792 recovery-plan contract.
- Kept the route read-only:
  - `mutation=false`
  - `subprocess_mutation_performed=false`
  - no new database table
  - no audit event emission yet
- Added route regression for:
  - missing service auth,
  - missing heartbeat recovery plan,
  - trace propagation,
  - invalid worker id problem response.

## Deferred

- Slice 0794: recovery action audit event emission.
- Slice 0795: operations dashboard recovery action integration.
- Slice 0796: acknowledgement/suppression policy.
- Slice 0799: static OpenAPI/schema hardening.

## Regression

```bash
./.venv/bin/pytest tests/test_nex_ag_operations.py -q -k "liveness_recovery_plan_route or liveness_recovery_plan or liveness_route_is_protected or process_control_route_is_protected"
```

Result: `6 passed, 196 deselected, 1 warning in 1.72s`.

```bash
./.venv/bin/pytest tests/test_nex_ag_operations.py -q
```

Result: `202 passed, 1 warning in 4.07s`.

```bash
./.venv/bin/pytest --cov --cov-branch --cov-report=term
```

Result: `5246 passed, 1 warning in 315.67s`.

Coverage totals: statement `98.70%` (`67251/68136`), branch `96.09%`
(`16035/16688`).
