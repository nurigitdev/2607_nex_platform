# Slice 0839: AG recovery notification privacy and operator runbook

## Objective

Freeze privacy regression and operator response guidance for the S84 recovery
notification policy before closure.

## Privacy Evidence

The evidence matrix covers policy disabled, eligible preview, delivery-ready
but unsent, acknowledged repeat, active suppression, critical bypass, below
threshold, and source unavailable outcomes. It injects credentials, database
URLs, provider data, comments, and idempotency values into source inputs and
rejects any value or forbidden key that reaches the output.

Every scenario confirms that provider invocation remains false. Actual external
notification delivery remains outside S84.

## Operator Runbook

| Signal | Response |
| --- | --- |
| Policy disabled | Review policy ownership before enabling notifications. |
| Below minimum severity | Treat as an intentional threshold decision. |
| Acknowledged repeat | Re-evaluate after the configured repeat window. |
| Active suppression | Wait for expiry or clear suppression after operator review. |
| Critical bypass | Review the critical signal immediately. |
| Source unavailable | Restore liveness and acknowledgement read models. |
| Delivery ready | Use the preview only; external delivery is a later boundary. |

## Verification

```bash
./.venv/bin/python \
  scripts/smoke/run_ag_recovery_notification_privacy_runbook_evidence.py \
  --summary
./.venv/bin/pytest \
  tests/test_ag_recovery_notification_privacy_runbook_evidence.py \
  -q --tb=short \
  --cov=run_ag_recovery_notification_privacy_runbook_evidence \
  --cov-branch --cov-report=term-missing
```

Evidence result:

```text
ag_recovery_notification_privacy_runbook=pass surfaces=8 privacy=True suppression=True runbook=True
```

Focused result: `6 passed`; privacy/runbook runner statement and branch
coverage are both `100%`.

Full regression result: `5572 passed`, `1 warning`.

- Statement coverage: `70420 / 71303` (`98.761622933116%`).
- Branch coverage: `16577 / 17228` (`96.221267703738%`).

The warning is the existing Starlette `TestClient` deprecation warning.
