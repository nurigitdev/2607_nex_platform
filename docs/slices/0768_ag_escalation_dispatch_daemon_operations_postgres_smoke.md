# Slice 0768: AG dispatch daemon operations PostgreSQL smoke evidence

## Objective

Prove the S77 dispatch daemon operations surface reads real persisted control
audit events from `nex_ag_test`.

## Scope

- Added an opt-in PostgreSQL smoke runner for the dispatch daemon operations
  surface.
- The runner applies `nex-ag` migrations against the configured test database
  before writing evidence rows.
- The runner writes succeeded, rejected, and failed daemon-control audit events
  through `SqlAlchemyOperationalEventStore`.
- The runner verifies the persisted events through:
  - the trace-scoped control history read model,
  - the AG operations dashboard `daemon_controls` section,
  - the AG operations issue-candidate projection.
- The runner deletes its smoke rows by `trace_id` after evidence collection and
  checks that raw probe values do not leak into evidence.
- No new database tables were introduced; the smoke reuses
  `service_operational_events`.

## Protected Smoke

```bash
NEX_AG_OPERATOR_REVIEW_ESCALATION_DISPATCH_DAEMON_OPERATIONS_POSTGRES_SMOKE=1 \
NEX_AG_TEST_DATABASE_URL=postgresql+psycopg://nex_ag_user:nuri1004@127.0.0.1:5432/nex_ag_test \
./.venv/bin/python scripts/smoke/run_ag_operator_review_escalation_dispatch_daemon_operations_postgres_smoke.py --summary
```

Expected evidence shape:

- `migration_ran=True`
- `events_emitted=True`
- `db_rows_persisted=True`
- `history_has_all_events=True`
- `dashboard_has_smoke_events=True`
- `issue_candidate_covers_failed_rejected=True`
- `raw_values_redacted=True`

## Regression

```bash
./.venv/bin/pytest tests/test_ag_operator_review_escalation_dispatch_daemon_operations_postgres_smoke.py -q --cov=run_ag_operator_review_escalation_dispatch_daemon_operations_postgres_smoke --cov-branch --cov-report=term-missing
```

Result: `11 passed in 1.93s`.

Coverage for the smoke runner: statement `100%`, branch `100%`.

```bash
NEX_AG_OPERATOR_REVIEW_ESCALATION_DISPATCH_DAEMON_OPERATIONS_POSTGRES_SMOKE=1 \
NEX_AG_TEST_DATABASE_URL=postgresql+psycopg://nex_ag_user:nuri1004@127.0.0.1:5432/nex_ag_test \
./.venv/bin/python scripts/smoke/run_ag_operator_review_escalation_dispatch_daemon_operations_postgres_smoke.py --summary
```

Result:
`ag_operator_review_escalation_dispatch_daemon_operations_postgres_smoke=pass service=nex-ag db_env=NEX_AG_TEST_DATABASE_URL events=3 failed=1 rejected=1 deleted_events=3`.

```bash
./.venv/bin/pytest --cov --cov-branch --cov-report=term
```

Result: `5124 passed, 1 warning in 302.27s`.

Coverage: statement `98.68%` (`65723/66605`), branch `96.05%`
(`15715/16362`).
