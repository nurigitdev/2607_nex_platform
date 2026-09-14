# Slice 0759: AG escalation dispatch daemon API admission guard evidence

## Objective

Harden the S76 protected dispatch daemon API with an operator-control admission
evidence pack. The evidence verifies that unsafe calls are rejected, dry-run
calls remain non-mutating, and only a confirmed tick-once can mutate dispatch
state.

## Scope

- Added
  `scripts/smoke/run_ag_operator_review_escalation_dispatch_daemon_api_admission_guard_evidence.py`.
- Covered six protected API scenarios:
  - missing authorization,
  - unsupported provider mode,
  - tick-once without confirmation,
  - disabled daemon,
  - confirmed dry-run tick-once,
  - confirmed mutating tick-once.
- Verified expected status codes, expected problem `error_code` values,
  mutation boundaries, accepted admission status, problem response shape, and
  absence of sensitive values in route responses.
- Added the admission evidence runner to the default quality gate.

## Regression

```bash
./.venv/bin/pytest tests/test_ag_operator_review_escalation_dispatch_daemon_api_admission_guard_evidence.py -q --cov=run_ag_operator_review_escalation_dispatch_daemon_api_admission_guard_evidence --cov-branch --cov-report=term-missing
```

Result: `5 passed`; admission guard evidence script coverage remained at
`100%` statement and `100%` branch coverage.

```bash
./.venv/bin/python scripts/smoke/run_ag_operator_review_escalation_dispatch_daemon_api_admission_guard_evidence.py --summary
```

Result:
`ag_operator_review_escalation_dispatch_daemon_api_admission_guard=pass scenarios=6 rejected=4 mutation_only_confirmed=True sensitive_absent=True`.
