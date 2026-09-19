# Slice 0859: AG Recovery Notification Live Privacy Runbook

## Goal

Freeze privacy checks, failure-mode evidence, and the operator sequence for S86
live recovery-notification delivery before the requirement is closed.

## Protected Failure Evidence

The evidence runner exercises these paths without a real external endpoint:

1. Live provider mode disabled by default.
2. Missing live-admission confirmation.
3. Missing execution confirmation, with the dispatch retained as `PENDING`.
4. Confirmed execution without an injected transport.
5. HTTP 503 results persisted as `RETRY_WAIT`.
6. HTTP 202 success persisted as `SUCCEEDED`.
7. Re-execution of a succeeded dispatch returned as `NOOP`.
8. Operations projection with request signatures and provider secrets excluded.

The runner fails if evidence includes a database URL/password, endpoint URL or
path, bearer token, raw notification payload, raw idempotency key, or sensitive
field name.

## Operator Runbook

1. Keep live mode disabled outside an approved execution window.
2. Verify the notification endpoint and provider profile readiness.
3. Approve live admission explicitly for the selected notification.
4. Persist the pending dispatch without invoking the provider.
5. Reconfirm the exact dispatch immediately before execution.
6. Inject the approved HTTP transport only at the execution boundary.
7. Treat `RETRY_WAIT` as bounded retry work and honor `next_attempt_at`.
8. Treat `SUCCEEDED` as terminal; repeated execution must remain `NOOP`.
9. Use loopback smoke until a real external endpoint is approved.
10. For PostgreSQL smoke, confirm cleanup leaves zero owned rows.

## Verification

```bash
./.venv/bin/python \
  scripts/smoke/run_ag_recovery_notification_live_privacy_runbook_evidence.py \
  --summary
```

Expected summary:

```text
ag_recovery_notification_live_privacy_runbook=pass surfaces=9 privacy=True failures=True runbook=True
```

```bash
./.venv/bin/pytest -q \
  tests/test_ag_recovery_notification_live_privacy_runbook_evidence.py \
  --cov=run_ag_recovery_notification_live_privacy_runbook_evidence \
  --cov-branch --cov-report=term-missing
```
