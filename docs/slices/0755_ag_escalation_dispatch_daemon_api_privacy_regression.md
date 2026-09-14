# Slice 0755: AG escalation dispatch daemon API privacy regression

## Intent

Harden the S76 protected dispatch daemon API route surface so tick-plan and
tick-once responses do not expose raw provider payloads, authorization values,
database URLs, storage paths, or idempotency keys.

## Implementation

- Added
  `scripts/smoke/run_ag_operator_review_escalation_dispatch_daemon_api_privacy_regression.py`.
- The regression exercises:
  - `GET /admin/v1/operator-review/dispatch-daemon/tick-plan`
  - `POST /admin/v1/operator-review/dispatch-daemon/tick-plan`
  - `POST /admin/v1/operator-review/dispatch-daemon/tick-once`
- The fixture seeds a safe pending dispatch while sending sensitive control
  payload fields through the protected routes, then verifies no forbidden
  values or raw sensitive keys appear in API responses.
- Added the regression to the default quality gate.

## Verification

```bash
./.venv/bin/pytest tests/test_ag_operator_review_escalation_dispatch_daemon_api_privacy_regression.py -q --cov=run_ag_operator_review_escalation_dispatch_daemon_api_privacy_regression --cov-branch --cov-report=term-missing
```

Result: `4 passed`, `100%` statement coverage, `100%` branch coverage for the
S76 API privacy regression script.

```bash
./.venv/bin/python scripts/smoke/run_ag_operator_review_escalation_dispatch_daemon_api_privacy_regression.py --summary
```

Result:
`ag_operator_review_escalation_dispatch_daemon_api_privacy_regression=pass surfaces=3 forbidden_absent=True raw_fields_absent=True`.
