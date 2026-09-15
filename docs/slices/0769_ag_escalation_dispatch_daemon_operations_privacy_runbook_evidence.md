# Slice 0769: AG dispatch daemon operations privacy/runbook evidence

## Objective

Lock the S77 dispatch daemon operations surfaces against sensitive-value drift
and ensure operators have stable runbook paths from the dashboard and issue
candidate projection.

## Scope

- Added a fast, non-DB evidence runner for the S77 operations surface:
  `run_ag_operator_review_escalation_dispatch_daemon_operations_privacy_runbook_evidence.py`.
- The runner seeds in-memory dispatch daemon control audit events and verifies:
  - trace-scoped control history,
  - dashboard `daemon_controls`,
  - operations issue candidate runbook/action hints,
  - static/runtime OpenAPI parity for the controls route.
- The runner checks forbidden values and forbidden raw keys are absent from the
  S77 surfaces.
- The runner is now part of `scripts/quality/run_quality_gate.sh`.
- No new database tables were introduced.

## Regression

```bash
./.venv/bin/pytest tests/test_ag_operator_review_escalation_dispatch_daemon_operations_privacy_runbook_evidence.py -q --cov=run_ag_operator_review_escalation_dispatch_daemon_operations_privacy_runbook_evidence --cov-branch --cov-report=term-missing
```

Result: `7 passed in 2.33s`.

Coverage for the evidence runner: statement `100%`, branch `100%`.

```bash
./.venv/bin/python scripts/smoke/run_ag_operator_review_escalation_dispatch_daemon_operations_privacy_runbook_evidence.py --summary
```

Result:
`ag_operator_review_escalation_dispatch_daemon_operations_privacy_runbook=pass surfaces=3 privacy=True runbooks=True route=True`.

```bash
./.venv/bin/pytest --cov --cov-branch --cov-report=term
```

Result: `5131 passed, 1 warning in 307.26s`.

Coverage: statement `98.68%` (`65854/66736`), branch `96.05%`
(`15745/16392`).
