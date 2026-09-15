# Slice 0789: AG dispatch daemon liveness privacy/runbook evidence

## Scope

- Added `scripts/smoke/run_ag_operator_review_escalation_dispatch_daemon_liveness_privacy_runbook_evidence.py`.
- The evidence runner validates stale and missing liveness paths for the AG
  dispatch daemon without using a database.
- It verifies the protected liveness route in both static and runtime OpenAPI,
  confirms required S79 documents through Slice 0788, and checks privacy
  surfaces for forbidden secrets, raw payloads, database URLs, and unsafe
  redaction flags.
- Registered the evidence runner in `scripts/quality/run_quality_gate.sh`.

## Runbook Coverage

- Stale heartbeat:
  - `ag.operator_review_dispatch_daemon_liveness.stale_heartbeat.v1`
  - `inspect_stale_dispatch_daemon_heartbeat`
- Missing heartbeat:
  - `ag.operator_review_dispatch_daemon_liveness.missing_heartbeat.v1`
  - `start_or_inspect_dispatch_daemon_process`

## Verification

- `./.venv/bin/pytest tests/test_ag_operator_review_escalation_dispatch_daemon_liveness_privacy_runbook_evidence.py -q`
  - `6 passed`
- `./.venv/bin/python scripts/smoke/run_ag_operator_review_escalation_dispatch_daemon_liveness_privacy_runbook_evidence.py --summary`
  - `ag_operator_review_escalation_dispatch_daemon_liveness_privacy_runbook=pass`
  - `surfaces=6`
  - `privacy=True`
  - `runbooks=True`
  - `route=True`
- `./.venv/bin/pytest --cov --cov-branch --cov-report=term`
  - `5230 passed, 1 warning`
  - statement coverage: `98.70%` (`67082/67967`)
  - branch coverage: `96.08%` (`15998/16650`)
