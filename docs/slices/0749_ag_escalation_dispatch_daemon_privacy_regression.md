# Slice 0749: AG dispatch execution daemon privacy regression

## Intent

Harden the dispatch daemon control, tick plan, event/log, and runtime projection
surfaces against accidental leakage before closing S75.

## Implementation

- Added
  `scripts/smoke/run_ag_operator_review_escalation_dispatch_daemon_privacy_regression.py`.
- The smoke injects sensitive values into control payloads, operator refs,
  dispatch metadata, worker-run internals, database URL-like values, and storage
  paths.
- The smoke verifies that public daemon surfaces expose only safe fields:
  policy, control request, admission, tick plan, event, log entry, and runtime
  projection.
- Added the privacy regression to the default quality gate.

## Verification

```bash
./.venv/bin/pytest tests/test_ag_operator_review_escalation_dispatch_daemon_privacy_regression.py -q --cov=run_ag_operator_review_escalation_dispatch_daemon_privacy_regression --cov-branch --cov-report=term-missing
```

Result: `4 passed`, `100%` statement coverage, `100%` branch coverage for the
privacy regression script.

```bash
./.venv/bin/python scripts/smoke/run_ag_operator_review_escalation_dispatch_daemon_privacy_regression.py --summary
```

Result:
`ag_operator_review_escalation_dispatch_daemon_privacy_regression=pass surfaces=7 forbidden_absent=True`.
