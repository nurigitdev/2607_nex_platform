# Slice 0809: AG dispatch liveness acknowledgement/suppression privacy/runbook

## Objective

Close the S81 privacy and operator-runbook evidence gap for the persisted
dispatch daemon liveness acknowledgement/suppression state.

## Scope

- Added a privacy/runbook evidence runner for the `ag_op_review_ack_state`
  action, list, detail, and recovery overlay surfaces.
- Verified that acknowledgement state mutation surfaces expose hashes and
  guardrails instead of raw comments, raw idempotency keys, provider payloads,
  tokens, or database URLs.
- Verified static and runtime OpenAPI route readiness for:
  - `POST /admin/v1/operator-review/dispatch-daemon/liveness/ack-state`;
  - `GET /admin/v1/operator-review/dispatch-daemon/liveness/ack-states`;
  - `GET /admin/v1/operator-review/dispatch-daemon/liveness/ack-states/{ack_state_id}`.
- Verified the short table name, redaction columns, and indexes from the
  `0802_ag_liveness_ack_state` migration.
- Added quality-gate wiring for the evidence runner.

## Decisions

- The evidence runner is static/in-memory by design. PostgreSQL persistence is
  already proven by Slice 0808, so this Slice focuses on privacy, route,
  runbook, and migration shape guarantees.
- The raw idempotency secret is used only as an input to the transition builder;
  the evidence surface keeps only hash-present booleans and guardrail flags.

## Regression

```bash
./.venv/bin/pytest tests/test_ag_operator_review_escalation_dispatch_daemon_liveness_ack_state_privacy_runbook_evidence.py -q --tb=short
```

Result: `7 passed in 3.46s`.

```bash
./.venv/bin/python scripts/smoke/run_ag_operator_review_escalation_dispatch_daemon_liveness_ack_state_privacy_runbook_evidence.py --summary
```

Result:
`ag_operator_review_escalation_dispatch_daemon_liveness_ack_state_privacy_runbook=pass surfaces=7 privacy=True routes=True table=ag_op_review_ack_state redaction=True`.

```bash
./.venv/bin/pytest tests/test_ag_operator_review_escalation_dispatch_daemon_liveness_ack_state_privacy_runbook_evidence.py tests/test_ag_operator_review_escalation_dispatch_daemon_liveness_ack_state_postgres_smoke.py tests/test_nex_ag_operator_review_liveness_ack.py tests/test_nex_ag_operator_review_liveness_ack_api.py tests/test_nex_ag_operations.py tests/test_contract_validation.py -q --tb=short
```

Result: `294 passed, 1 warning in 11.60s`.

```bash
./.venv/bin/pytest --cov --cov-branch --cov-report=term
```

Result: `5342 passed, 1 warning in 338.35s`.

Coverage JSON: `/tmp/nex_platform_0809_coverage.json`

- Statement coverage: `68662 / 69545 = 98.73031849881372%`.
- Branch coverage: `16329 / 16980 = 96.1660777385159%`.
- New evidence runner coverage: `170 / 170 statements`, `28 / 28 branches`.
