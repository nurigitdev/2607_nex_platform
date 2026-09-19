# Slice 0854: AG recovery notification live delivery API guardrails

## Objective

Extend the protected recovery-notification delivery POST so an explicitly
confirmed and configured live request may be persisted without invoking its
provider.

## Implementation

- Added `confirm_live_delivery` request validation.
- Live notification, email, and webhook requests build the S86 admission from
  the existing environment-backed dispatch provider configuration.
- Explicit confirmation, effective live mode, live enablement, endpoint
  readiness, and profile/channel compatibility must all pass before handoff.
- The route persists a `PENDING` outbox row and reports live admission status,
  but performs no network call.
- MOCK requests remain on the existing S85 path regardless of the live
  confirmation field.
- Endpoint URLs and provider tokens are absent from responses and persistence.

## Verification

```bash
./.venv/bin/pytest -q --tb=short \
  tests/test_nex_ag_recovery_notification_live_delivery_api.py \
  tests/test_nex_ag_recovery_notification_delivery_api.py \
  --cov=nex_ag.operations --cov=nex_ag.recovery_notification_delivery \
  --cov-branch
```
