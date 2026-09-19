# Slice 0853: AG recovery notification live dispatch handoff

## Objective

Wire an admitted S86 recovery notification into the existing dispatch planner
without opening live channels for any existing caller by default.

## Implementation

- Added a default-false `allow_live_channel` internal planner argument.
- The generic escalation planner continues returning
  `live_channel_deferred` unless that argument is explicitly true.
- The recovery notification handoff accepts an optional S86 live admission and
  verifies its schema, status, notification plan, case, escalation, channel,
  provider profile, mode, and intent before opening the planner path.
- Live admission provenance is stored as a schema-version marker only; endpoint
  values, tokens, and raw payloads are excluded.
- No persistence, provider invocation, route, table, or migration is added.

## Verification

```bash
./.venv/bin/pytest -q --tb=short \
  tests/test_nex_ag_recovery_notification_live_handoff.py \
  tests/test_nex_ag_recovery_notification_dispatch_handoff.py \
  tests/test_nex_ag_operator_review_cases.py \
  --cov=nex_ag.recovery_notification_delivery \
  --cov=nex_ag.operator_review_cases --cov-branch
```
