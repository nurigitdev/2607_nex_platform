# Slice 0833: AG recovery notification eligibility evaluation

## Objective

Evaluate recovery notification eligibility from the existing recovery plan and
effective acknowledgement/suppression state without sending a notification.

## Decision Order

1. Disabled policy is ineligible.
2. A recovery plan with no action is ineligible.
3. Severity below the configured minimum is ineligible.
4. `ACKNOWLEDGED` suppresses a repeated notification.
5. Active `SUPPRESSED` suppresses the notification.
6. `CRITICAL` may bypass active suppression only when policy permits it.
7. `EXPIRED`, `CLEARED`, or absent state does not block an otherwise eligible
   signal.

The highest severity among recovery actions drives the decision. Invalid input
shape and timestamps produce normalized policy errors.

## Guardrails

- `delivery_authorized_by_policy` is only a policy result.
- `provider_invocation_performed` always remains false in S84.
- No raw recovery payload, operator comment, idempotency key, endpoint, token,
  or database URL is copied into the decision.
- No database mutation or new table is introduced.

## Verification

```bash
./.venv/bin/pytest \
  tests/test_nex_ag_recovery_notification_policy.py \
  tests/test_nex_ag_recovery_notification_eligibility.py \
  -q --tb=short --cov=nex_ag.recovery_notification_policy \
  --cov-branch --cov-report=term-missing
```

Focused regression result: `24 passed`.

Full regression result: `5525 passed, 1 warning`.

- Statement coverage: `70111 / 70994 = 98.756232921092%`.
- Branch coverage: `16527 / 17178 = 96.210268948655%`.
- Policy/eligibility module statement/branch coverage: `100% / 100%`.
