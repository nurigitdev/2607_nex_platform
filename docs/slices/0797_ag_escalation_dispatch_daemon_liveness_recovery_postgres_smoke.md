# Slice 0797: AG dispatch liveness recovery PostgreSQL smoke evidence

## Objective

Add protected PostgreSQL smoke evidence for the S80 dispatch daemon liveness
recovery path: persisted heartbeat input, recovery-plan read model, audit event
emission, dashboard recovery section, issue-candidate acknowledgement policy,
and cleanup.

## Scope

- Added
  `scripts/smoke/run_ag_operator_review_escalation_dispatch_daemon_liveness_recovery_postgres_smoke.py`.
- The smoke runner:
  - requires explicit opt-in through
    `NEX_AG_OPERATOR_REVIEW_ESCALATION_DISPATCH_DAEMON_LIVENESS_RECOVERY_POSTGRES_SMOKE=1`,
  - runs `nex-ag` test migrations before execution,
  - writes a stale dispatch daemon heartbeat into `service_worker_heartbeats`,
  - emits a planned recovery audit event into `service_operational_events`,
  - verifies dashboard `daemon_recovery` and liveness issue-candidate policy,
  - restores or deletes the heartbeat row and deletes smoke audit events.
- Added regression coverage for skip/failure/success/cleanup/redaction/helper
  paths.

## Deferred

- Slice 0798: operator acknowledgement/suppression state persistence decision.
- Slice 0799: static OpenAPI/schema hardening for recovery routes.
- Slice 0800: S80 recovery foundation closure checkpoint.

## Regression

```bash
./.venv/bin/pytest tests/test_ag_operator_review_escalation_dispatch_daemon_liveness_recovery_postgres_smoke.py -q
```

Result: `12 passed in 0.57s`.

```bash
./.venv/bin/pytest tests/test_ag_operator_review_escalation_dispatch_daemon_liveness_recovery_postgres_smoke.py -q --cov=run_ag_operator_review_escalation_dispatch_daemon_liveness_recovery_postgres_smoke --cov-branch --cov-report=term-missing
```

Result: `12 passed in 1.12s`; script coverage statement/branch `100%`.

```bash
NEX_AG_OPERATOR_REVIEW_ESCALATION_DISPATCH_DAEMON_LIVENESS_RECOVERY_POSTGRES_SMOKE=1 \
NEX_AG_TEST_DATABASE_URL='postgresql+psycopg://nex_ag_user:nuri1004@127.0.0.1:5432/nex_ag_test' \
./.venv/bin/python scripts/smoke/run_ag_operator_review_escalation_dispatch_daemon_liveness_recovery_postgres_smoke.py --summary
```

Result:
`ag_operator_review_escalation_dispatch_daemon_liveness_recovery_postgres_smoke=pass service=nex-ag db_env=NEX_AG_TEST_DATABASE_URL backend=postgresql heartbeat_rows=1 event_rows=1 recovery=STALE dashboard=ACTION_RECOMMENDED issue_ack=ACTIONABLE deleted_audit_event_rows=1`.

```bash
./.venv/bin/pytest --cov --cov-branch --cov-report=term
```

Result: `5261 passed, 1 warning in 293.78s`.

Coverage totals: statement `98.71%` (`67554/68437`), branch `96.12%`
(`16111/16762`).
