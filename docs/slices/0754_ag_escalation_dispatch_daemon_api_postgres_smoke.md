# Slice 0754: AG escalation dispatch daemon API PostgreSQL smoke

## Intent

Add protected smoke evidence that the S76 dispatch daemon API routes work
against the real `nex_ag_test` PostgreSQL database.

## Implementation

- Added
  `scripts/smoke/run_ag_operator_review_escalation_dispatch_daemon_api_postgres_smoke.py`.
- The smoke applies AG test migrations, seeds one operator review case,
  escalation, and pending dispatch row, then calls:
  - `GET /admin/v1/operator-review/dispatch-daemon/tick-plan`
  - `POST /admin/v1/operator-review/dispatch-daemon/tick-once`
- The smoke verifies that tick-plan sees the seeded dispatch, tick-once
  completes through the route, the dispatch row reaches `SUCCEEDED`, execution
  metadata is persisted, raw values/idempotency keys are not stored in evidence,
  and cleanup removes smoke rows.
- No new table or migration is introduced.

## Verification

```bash
./.venv/bin/pytest tests/test_ag_operator_review_escalation_dispatch_daemon_api_postgres_smoke.py
```

Result: `6 passed`.

```bash
NEX_AG_OPERATOR_REVIEW_ESCALATION_DISPATCH_DAEMON_API_POSTGRES_SMOKE=1 \
NEX_AG_TEST_DATABASE_URL=... \
./.venv/bin/python scripts/smoke/run_ag_operator_review_escalation_dispatch_daemon_api_postgres_smoke.py --summary
```

Result:
`ag_operator_review_escalation_dispatch_daemon_api_postgres_smoke=pass service=nex-ag db_env=NEX_AG_TEST_DATABASE_URL tick_once=COMPLETED dispatches=1 metadata=1 deleted_dispatches=1`.
