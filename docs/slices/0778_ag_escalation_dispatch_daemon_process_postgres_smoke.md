# Slice 0778: AG dispatch daemon process PostgreSQL smoke evidence

## Intent

Prove the S78 dispatch daemon process surface against the real `nex_ag_test`
PostgreSQL database while keeping subprocess mutation disabled and evidence
redacted.

## Implementation

- Added opt-in smoke runner:
  `scripts/smoke/run_ag_operator_review_escalation_dispatch_daemon_process_postgres_smoke.py`.
- The smoke:
  - runs `nex-ag` migrations against `NEX_AG_TEST_DATABASE_URL`
  - emits dispatch daemon process lifecycle events through the CLI `run_once`
    path
  - verifies the rows directly in `service_operational_events`
  - checks the operations dashboard `daemon_process` subsection
  - checks the protected process-control projection is contract-only
  - deletes smoke rows by `trace_id`
- Added the runner to `scripts/quality/run_quality_gate.sh`; it skips unless
  `NEX_AG_OPERATOR_REVIEW_ESCALATION_DISPATCH_DAEMON_PROCESS_POSTGRES_SMOKE=1`.
- No new database table is introduced.

## Verification

```bash
./.venv/bin/pytest tests/test_ag_operator_review_escalation_dispatch_daemon_process_postgres_smoke.py -q --cov=run_ag_operator_review_escalation_dispatch_daemon_process_postgres_smoke --cov-branch --cov-report=term
```

Result: `11 passed in 1.11s`.

Coverage for the smoke runner: statement `100%`, branch `100%`.

Actual `nex_ag_test` PostgreSQL smoke:

```bash
NEX_AG_OPERATOR_REVIEW_ESCALATION_DISPATCH_DAEMON_PROCESS_POSTGRES_SMOKE=1 \
NEX_AG_TEST_DATABASE_URL='postgresql+psycopg://nex_ag_user:***@127.0.0.1:5432/nex_ag_test' \
./.venv/bin/python scripts/smoke/run_ag_operator_review_escalation_dispatch_daemon_process_postgres_smoke.py --summary
```

Result:
`ag_operator_review_escalation_dispatch_daemon_process_postgres_smoke=pass service=nex-ag db_env=NEX_AG_TEST_DATABASE_URL events=2 process=DISABLED control_action=status_probe deleted_events=2`.
