# Slice 0758: AG escalation dispatch daemon API runbook evidence

## Intent

Add an operator-oriented evidence pack for the S76 dispatch daemon API so the
protected control routes are easy to audit before closure.

## Implementation

- Added
  `scripts/smoke/run_ag_operator_review_escalation_dispatch_daemon_api_runbook_evidence.py`.
- The evidence verifies:
  - static OpenAPI route operation IDs are present,
  - runtime FastAPI OpenAPI route operation IDs match,
  - tick-plan routes are non-mutating,
  - tick-once requires confirmation,
  - sensitive control request fields are absent from the published contract,
  - S76 docs and smoke/privacy evidence hooks are present.
- Added the runbook evidence to the default quality gate.
- Added the opt-in PostgreSQL API smoke runner to the default quality gate; it
  exits successfully as `SKIPPED` unless the protected test DB smoke env is
  enabled.

## Verification

```bash
./.venv/bin/python scripts/smoke/run_ag_operator_review_escalation_dispatch_daemon_api_runbook_evidence.py --summary
```

Result:
`ag_operator_review_escalation_dispatch_daemon_api_runbook=pass routes=3 runtime_routes_ready=True sensitive_fields_absent=True`.

```bash
./.venv/bin/pytest tests/test_ag_operator_review_escalation_dispatch_daemon_api_runbook_evidence.py -q --cov=run_ag_operator_review_escalation_dispatch_daemon_api_runbook_evidence --cov-branch --cov-report=term-missing
```

Result: `4 passed`, `100%` statement coverage, `100%` branch coverage for the
runbook evidence script.
