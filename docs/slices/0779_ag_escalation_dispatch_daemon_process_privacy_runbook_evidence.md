# Slice 0779: AG dispatch daemon process privacy/runbook evidence

## Intent

Prove the S78 dispatch daemon process dashboard, process-control projection, and
lifecycle evidence are safe for operators: no raw secrets, clear runbook IDs,
and static/runtime route parity for protected process controls.

## Implementation

- Added privacy/runbook runner:
  `scripts/smoke/run_ag_operator_review_escalation_dispatch_daemon_process_privacy_runbook_evidence.py`.
- The runner verifies:
  - dashboard `daemon_process` readiness
  - process-control projection remains contract-only and non-mutating
  - lifecycle event evidence includes started/completed/blocked process states
  - runbook IDs and operator actions are present
  - static and runtime OpenAPI route parity for
    `POST /admin/v1/operator-review/dispatch-daemon/process-controls`
  - S78 prerequisite docs through Slice 0778 are present
  - forbidden values/keys and unsafe redaction flags are absent
- Added the runner to `scripts/quality/run_quality_gate.sh`.
- No new database table is introduced.

## Verification

```bash
./.venv/bin/pytest tests/test_ag_operator_review_escalation_dispatch_daemon_process_privacy_runbook_evidence.py -q --cov=run_ag_operator_review_escalation_dispatch_daemon_process_privacy_runbook_evidence --cov-branch --cov-report=term
```

Result: `7 passed in 2.38s`.

Coverage for the privacy/runbook runner: statement `100%`, branch `100%`.

```bash
./.venv/bin/python scripts/smoke/run_ag_operator_review_escalation_dispatch_daemon_process_privacy_runbook_evidence.py --summary
```

Result:
`ag_operator_review_escalation_dispatch_daemon_process_privacy_runbook=pass surfaces=4 privacy=True runbooks=True route=True`.
