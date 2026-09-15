# Slice 0788: AG dispatch daemon liveness PostgreSQL smoke evidence

## Scope

- Added a protected PostgreSQL smoke runner for AG dispatch daemon liveness:
  `scripts/smoke/run_ag_operator_review_escalation_dispatch_daemon_liveness_postgres_smoke.py`.
- The runner requires
  `NEX_AG_OPERATOR_REVIEW_ESCALATION_DISPATCH_DAEMON_LIVENESS_POSTGRES_SMOKE=1`
  and `NEX_AG_TEST_DATABASE_URL`, runs AG migrations first, and connects to the
  real `nex_ag_test` PostgreSQL database.
- It upserts the canonical `ag-dispatch-execution-daemon` heartbeat through
  `SqlAlchemyWorkerHeartbeatStore`, validates fresh/stale liveness projections,
  validates the operations dashboard liveness section, validates the stale
  liveness issue candidate, and then restores or deletes the smoke heartbeat.
- Registered the runner in `scripts/quality/run_quality_gate.sh` after the
  Slice 0781 liveness boundary audit.

## Persistence Boundary

- Source table: `service_worker_heartbeats`.
- No new table is introduced.
- If a prior test heartbeat exists in `nex_ag_test`, the smoke restores it;
  otherwise it deletes the smoke row.
- Evidence stores the database env name and redacted URL only.

## Verification

- `./.venv/bin/pytest tests/test_ag_operator_review_escalation_dispatch_daemon_liveness_postgres_smoke.py -q`
  - `12 passed`
- Protected live smoke against the real `nex_ag_test` database:
  - `ag_operator_review_escalation_dispatch_daemon_liveness_postgres_smoke=pass`
  - `backend=postgresql`
  - `rows=1`
  - `fresh=FRESH`
  - `stale=STALE`
  - `issue=STALE`
  - `deleted_heartbeat_rows=1`
- `./.venv/bin/pytest tests/test_nex_ag_operations.py -q -k "dispatch_daemon_liveness"`
  - `5 passed, 193 deselected`
- `./.venv/bin/pytest tests/test_contract_validation.py -q`
  - `28 passed`
- `./.venv/bin/pytest --cov --cov-branch --cov-report=term`
  - `5224 passed, 1 warning`
  - statement coverage: `98.69%` (`66926/67811`)
  - branch coverage: `96.08%` (`15966/16618`)
