# Slice 0860: S86 AG Recovery Notification Live Delivery Closure

## Goal

Close S86 by proving that recovery notifications can use the established AG
dispatch outbox and live HTTP runtime without adding a table or enabling an
unapproved external endpoint.

## Closed Boundary

- Source of record: existing `ag_op_esc_dispatches`.
- Live channel: notification-compatible profiles only.
- Admission: live mode, endpoint readiness, provider-profile compatibility,
  and explicit confirmation are required.
- Persistence and execution remain separate operator actions.
- Execution: one selected dispatch, bounded worker batch, injected transport,
  existing retry/state machine, and a second explicit confirmation.
- Evidence: safe hashes, provider mode, HTTP status, retry state, and redacted
  projections only.
- Real provider proof: urllib transport against a local loopback HTTP server.
- PostgreSQL proof: opt-in execution against `nex_ag_test`, including migration,
  insert/select/update, HTTP 202, and cleanup verification.
- External production notification endpoint activation remains deferred.

No new table or index was introduced in S86.

## Protected Closure

The regular quality gate runs the real local loopback transport and keeps the
PostgreSQL smoke disabled:

```text
s86_ag_recovery_notification_live_delivery_closure=pass slice_range=0851-0860 loopback=PASS postgres=SKIPPED privacy=PASS
```

For an actual test-database closure run:

```bash
NEX_AG_RECOVERY_NOTIFICATION_LIVE_POSTGRES_SMOKE=1 \
NEX_AG_TEST_DATABASE_URL='postgresql+psycopg://nex_ag_user:***@127.0.0.1:5432/nex_ag_test' \
./.venv/bin/python \
  scripts/smoke/run_s86_ag_recovery_notification_live_delivery_closure.py \
  --summary
```

Expected protected result:

```text
s86_ag_recovery_notification_live_delivery_closure=pass slice_range=0851-0860 loopback=PASS postgres=PASS privacy=PASS
```

## Verification

```bash
./.venv/bin/pytest -q \
  tests/test_s86_ag_recovery_notification_live_delivery_closure.py \
  --cov=run_s86_ag_recovery_notification_live_delivery_closure \
  --cov-branch --cov-report=term-missing
```
