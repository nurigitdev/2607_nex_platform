# Slice 0852: AG recovery notification live delivery admission

## Objective

Add a pure admission/configuration contract that must pass before an S85
recovery notification may enter the live HTTP delivery path.

## Implementation

- Added `build_recovery_notification_live_admission(...)`.
- Requires an admitted S85 delivery contract and limits recovery notifications
  to `NOTIFICATION`, `EMAIL`, or `WEBHOOK`.
- Requires explicit confirmation, configured and effective `live_http` mode,
  the existing live-provider enable guard, a configured notification endpoint,
  and a provider profile compatible with the selected channel.
- Returns only readiness booleans and safe identifiers. Endpoint values,
  authorization material, raw notification payloads, and provider secrets are
  never returned.
- Performs no persistence, provider invocation, or network access.

## Verification

```bash
./.venv/bin/pytest -q --tb=short \
  tests/test_nex_ag_recovery_notification_live_admission.py \
  --cov=nex_ag.recovery_notification_delivery \
  --cov-branch --cov-report=term-missing
```
