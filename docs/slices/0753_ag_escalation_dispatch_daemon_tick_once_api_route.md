# Slice 0753: AG escalation dispatch daemon tick-once API route

## Intent

Implement the protected, mutating tick-once API route for AG operator review
escalation dispatch daemon execution.

## Implementation

- Added `POST /admin/v1/operator-review/dispatch-daemon/tick-once`.
- Reused daemon control request/admission and tick execution services.
- The route rejects tick-once with `409` unless the daemon policy is enabled and
  `confirm_tick=True`.
- `dry_run=True` executes planning/provider simulation but does not mutate
  dispatch state.
- Confirmed non-dry-run execution updates existing records in
  `ag_op_esc_dispatches` through the existing operator review dispatch action
  service.
- No new table, migration, background loop, or external live endpoint is
  introduced.

## Verification

```bash
./.venv/bin/pytest tests/test_nex_ag_operations.py -k 'dispatch_daemon_tick'
```

Result: `7 passed`; tick-plan and tick-once route authorization, guardrails,
dry-run behavior, mutation behavior, and redaction were verified.
