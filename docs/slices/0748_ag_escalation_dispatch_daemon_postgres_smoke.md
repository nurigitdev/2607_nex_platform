# Slice 0748: AG dispatch execution daemon PostgreSQL smoke evidence

## Intent

Prove the protected dispatch daemon tick path against the real `nex_ag_test`
PostgreSQL database while keeping the outbound provider call local and
deterministic through a loopback HTTP server.

## Implementation

- Added
  `scripts/smoke/run_ag_operator_review_escalation_dispatch_daemon_postgres_smoke.py`.
- The smoke runs service migrations, seeds an operator review case, escalation,
  and two escalation dispatches in PostgreSQL.
- The smoke verifies protected control admission, daemon tick execution,
  loopback live HTTP provider calls, persisted dispatch metadata, operations
  dashboard execution summary, daemon runtime projection, event/log projection,
  redaction checks, and cleanup.
- Added the script to the default quality gate as a skip-safe smoke hook.

## Verification

```bash
./.venv/bin/pytest tests/test_ag_operator_review_escalation_dispatch_daemon_postgres_smoke.py -q --cov=run_ag_operator_review_escalation_dispatch_daemon_postgres_smoke --cov-branch --cov-report=term-missing
```

Result: `7 passed`, `100%` statement coverage, `100%` branch coverage for the
daemon PostgreSQL smoke script.

```bash
./.venv/bin/python scripts/smoke/run_ag_operator_review_escalation_dispatch_daemon_postgres_smoke.py --summary
```

Result:
`ag_operator_review_escalation_dispatch_daemon_postgres_smoke=skipped reason=NEX_AG_OPERATOR_REVIEW_ESCALATION_DISPATCH_DAEMON_POSTGRES_SMOKE is not enabled.`

```bash
NEX_AG_OPERATOR_REVIEW_ESCALATION_DISPATCH_DAEMON_POSTGRES_SMOKE=1 \
NEX_AG_TEST_DATABASE_URL='postgresql+psycopg://nex_ag_user:nuri1004@127.0.0.1:5432/nex_ag_test' \
./.venv/bin/python scripts/smoke/run_ag_operator_review_escalation_dispatch_daemon_postgres_smoke.py --summary
```

Result:
`ag_operator_review_escalation_dispatch_daemon_postgres_smoke=pass requests=2 ticks=1 dispatches=2 metadata=2 deleted_dispatches=2`.
