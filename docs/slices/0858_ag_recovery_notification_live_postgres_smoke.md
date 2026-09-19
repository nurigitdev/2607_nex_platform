# Slice 0858: AG Recovery Notification Live PostgreSQL Smoke

## Goal

Prove the S86 recovery-notification live HTTP path against the actual
`nex_ag_test` PostgreSQL database while retaining a local loopback HTTP server
instead of an external notification endpoint.

## Boundary

- The smoke is disabled unless
  `NEX_AG_RECOVERY_NOTIFICATION_LIVE_POSTGRES_SMOKE=1` is set.
- `NEX_AG_TEST_DATABASE_URL` must select `nex_ag_test`.
- AG migrations run before the smoke records are created.
- The normal case, escalation, dispatch outbox, live admission, worker, and
  urllib HTTP transport paths are used.
- The provider target is a temporary `127.0.0.1` loopback server returning HTTP
  202. A real notification endpoint remains deferred.
- Evidence contains no database credential, endpoint URL/path, bearer token,
  raw notification payload, or idempotency key.
- All owned case, escalation, and dispatch rows are removed and the zero-row
  result is checked before success is reported.

## Evidence

The smoke proves one pending dispatch is persisted, exactly one HTTP request is
received, the dispatch transitions to `SUCCEEDED`, and PostgreSQL stores safe
`live_http` plus HTTP 202 execution metadata.

```bash
NEX_AG_RECOVERY_NOTIFICATION_LIVE_POSTGRES_SMOKE=1 \
NEX_AG_TEST_DATABASE_URL='postgresql+psycopg://nex_ag_user:***@127.0.0.1:5432/nex_ag_test' \
./.venv/bin/python \
  scripts/smoke/run_ag_recovery_notification_live_postgres_smoke.py --summary
```

The regular quality gate invokes the script without opt-in, where it reports a
safe skip and performs no database or network work.

## Verification

```bash
./.venv/bin/pytest -q \
  tests/test_ag_recovery_notification_live_postgres_smoke.py \
  --cov=run_ag_recovery_notification_live_postgres_smoke \
  --cov-branch --cov-report=term-missing
```
