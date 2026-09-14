# Slice 0738: AG dispatch live HTTP PostgreSQL smoke

## Intent

Prove the S74 live HTTP transport path through the AG dispatch worker and real
`nex_ag_test` PostgreSQL persistence while still using only a local loopback HTTP
server.

## Implementation

- Added
  `scripts/smoke/run_ag_operator_review_escalation_dispatch_live_http_postgres_smoke.py`.
- The smoke is protected by
  `NEX_AG_OPERATOR_REVIEW_ESCALATION_DISPATCH_LIVE_HTTP_POSTGRES_SMOKE=1`.
- The script runs AG migrations, seeds a case, escalation, notification dispatch,
  and incident dispatch, executes the worker with injected live HTTP loopback
  transport, verifies persisted execution metadata, and cleans up all smoke rows.
- Evidence redacts the database URL, bearer token, endpoint URL, idempotency
  keys, and raw provider payload fingerprints.
- Added a skip-safe quality gate hook.

## Verification

```bash
./.venv/bin/pytest tests/test_ag_operator_review_escalation_dispatch_live_http_postgres_smoke.py -q --cov=run_ag_operator_review_escalation_dispatch_live_http_postgres_smoke --cov-branch --cov-report=term-missing
```

Result: `8 passed`, `100%` statement coverage, `100%` branch coverage for the
live HTTP PostgreSQL smoke script.

```bash
NEX_AG_OPERATOR_REVIEW_ESCALATION_DISPATCH_LIVE_HTTP_POSTGRES_SMOKE=1 NEX_AG_TEST_DATABASE_URL='<redacted nex_ag_test URL>' ./.venv/bin/python scripts/smoke/run_ag_operator_review_escalation_dispatch_live_http_postgres_smoke.py --summary
```

Result:
`ag_operator_review_escalation_dispatch_live_http_postgres_smoke=pass requests=2 dispatches=2 metadata=2 deleted_dispatches=2`.
