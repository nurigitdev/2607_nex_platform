# Slice 0832: AG recovery notification policy configuration

## Objective

Define a deterministic and environment-configurable S84 notification policy
without invoking an outbound provider.

## Policy Defaults

- Policy evaluation is enabled so operators can preview decisions.
- Delivery is disabled by default.
- Minimum eligible severity is `WARNING`.
- Repeat suppression window is 900 seconds, bounded to 60-86400 seconds.
- `CRITICAL` may bypass active suppression by default; S84 only reports that
  decision and still performs no delivery.
- The only S84 preview channel is `operations_dashboard`.

## Environment

- `NEX_AG_RECOVERY_NOTIFICATION_POLICY_ENABLED`
- `NEX_AG_RECOVERY_NOTIFICATION_DELIVERY_ENABLED`
- `NEX_AG_RECOVERY_NOTIFICATION_MIN_SEVERITY`
- `NEX_AG_RECOVERY_NOTIFICATION_REPEAT_WINDOW_SECONDS`
- `NEX_AG_RECOVERY_NOTIFICATION_CRITICAL_BYPASS_SUPPRESSION`

Unknown booleans, invalid severity names, and invalid integers fall back to
safe defaults. Repeat windows are clamped to documented bounds.

## Guardrails

- No new table, route, provider call, dispatch record, or retry is introduced.
- Provider endpoints, tokens, database URLs, raw comments, idempotency keys,
  and raw payloads are excluded.
- Delivery enablement is represented for future integration but has no delivery
  effect in S84.

## Verification

```bash
./.venv/bin/pytest \
  tests/test_nex_ag_recovery_notification_policy.py \
  -q --tb=short --cov=nex_ag.recovery_notification_policy \
  --cov-branch --cov-report=term-missing
```

Focused regression result: `7 passed`.

Full regression result: `5508 passed, 1 warning`.

- Statement coverage: `70049 / 70932 = 98.755145773417%`.
- Branch coverage: `16503 / 17154 = 96.204966771598%`.
- Policy module statement/branch coverage: `100% / 100%`.
