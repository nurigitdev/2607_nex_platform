# Slice 0752: AG escalation dispatch daemon tick-plan API route

## Intent

Implement the non-mutating, protected API route for AG operator review
escalation dispatch daemon tick planning.

## Implementation

- Added `GET /admin/v1/operator-review/dispatch-daemon/tick-plan`.
- Added `POST /admin/v1/operator-review/dispatch-daemon/tick-plan`.
- Both routes reuse `nex_runtime.validate_authorization_header` through the AG
  operations authorization helper.
- The route builds a safe control request/admission envelope, reads candidates
  from the existing `ag_op_esc_dispatches` source, and returns the daemon
  tick-plan projection without mutating dispatch state.
- Query/body policy overrides are limited to `enabled`, `dry_run`,
  `batch_limit`, and `provider_mode`; sensitive payload fields are ignored by
  the projection.
- No new table, migration, background loop, or external dispatch call is
  introduced.

## Verification

```bash
./.venv/bin/pytest tests/test_nex_ag_operations.py -k 'dispatch_daemon_tick_plan'
```

Result: `3 passed`; route authorization, error mapping, read-only behavior, and
redaction were verified.
