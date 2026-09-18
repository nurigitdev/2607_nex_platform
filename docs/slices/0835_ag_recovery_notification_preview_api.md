# Slice 0835: AG recovery notification protected preview API

## Objective

Expose the current S84 notification policy decision through a protected,
read-only NeX-AG API.

## Route

`GET /admin/v1/operator-review/dispatch-daemon/liveness/recovery-notification-preview`

The route:

1. builds the current dispatch-daemon liveness projection;
2. builds the existing recovery plan with persisted ack-state overlay;
3. evaluates notification eligibility;
4. returns the redacted notification preview plan.

Missing authorization is rejected. Invalid liveness filters and policy errors
use the existing AG problem response contract.

## Guardrails

- The route performs no mutation and emits no outbound provider request.
- Active persisted suppression is reflected in the preview.
- Recovery-plan audit events are not duplicated by this derived preview route.
- No new table, dispatch record, retry, retention, or deletion path is added.

## Verification

```bash
./.venv/bin/pytest \
  tests/test_nex_ag_recovery_notification_preview_api.py \
  tests/test_nex_ag_recovery_notification_policy.py \
  tests/test_nex_ag_recovery_notification_eligibility.py \
  tests/test_nex_ag_recovery_notification_plan.py \
  -q --tb=short
```

Focused regression result: `37 passed, 1 warning`.

Full regression result: `5538 passed, 1 warning`.

- Statement coverage: `70163 / 71046 = 98.757143259297%`.
- Branch coverage: `16539 / 17190 = 96.212914485166%`.
