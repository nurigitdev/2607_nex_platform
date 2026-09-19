# Slice 0857: AG recovery notification live loopback smoke

## Objective

Prove the S86 live path through a real local HTTP request without requiring an
external notification endpoint.

## Evidence

- Added opt-in smoke environment
  `NEX_AG_RECOVERY_NOTIFICATION_LIVE_LOOPBACK_SMOKE=1`.
- Builds the recovery plan, S85 admission, S86 live admission, outbox handoff,
  persistence, targeted live execution, and recovery delivery projection.
- Uses `UrllibDispatchProviderHttpTransport` against an ephemeral
  `127.0.0.1` HTTP server.
- Verifies exactly one POST, Authorization header presence, safe envelope
  content, HTTP 202 mapping, `SUCCEEDED` persistence, and live result
  projection.
- Evidence stores no endpoint path, token, Authorization value, raw payload,
  or database URL.

## Verification

```bash
NEX_AG_RECOVERY_NOTIFICATION_LIVE_LOOPBACK_SMOKE=1 \
  ./.venv/bin/python \
  scripts/smoke/run_ag_recovery_notification_live_loopback_smoke.py --summary
./.venv/bin/pytest -q --tb=short \
  tests/test_ag_recovery_notification_live_loopback_smoke.py \
  --cov=run_ag_recovery_notification_live_loopback_smoke \
  --cov-branch --cov-report=term-missing
```
