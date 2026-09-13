# Slice 0710: AG Operator Review Escalation Dispatch PostgreSQL Smoke

## Intent

Validate the S71 escalation dispatch outbox against the real AG PostgreSQL test
database, not only in-memory or SQLite regression paths.

## Implementation

- Added
  `scripts/smoke/run_ag_operator_review_escalation_dispatch_postgres_smoke.py`.
- The smoke is protected by
  `NEX_AG_OPERATOR_REVIEW_ESCALATION_DISPATCH_POSTGRES_SMOKE=1` and reads
  `NEX_AG_TEST_DATABASE_URL`.
- The smoke runs `nex-ag` migrations first, then uses PostgreSQL-backed case,
  escalation, dispatch, and operational event stores.
- It creates a case and escalation, creates an escalation dispatch through the
  protected AG route, replays the idempotent create, starts the dispatch through
  the action route, replays the action, reads list/detail/dashboard/issue
  projections, directly observes PostgreSQL rows, and cleans up smoke rows.
- Evidence redacts raw DB URLs, idempotency keys, provider payloads,
  notification payloads, external incident payloads, and raw action comments.

## Evidence

- `PYTHONPATH=services/_shared:services/nex-ag:scripts/db:scripts/smoke ./.venv/bin/pytest tests/test_ag_operator_review_escalation_dispatch_postgres_smoke.py -q --cov=run_ag_operator_review_escalation_dispatch_postgres_smoke --cov-branch --cov-report=term-missing`
- `NEX_AG_OPERATOR_REVIEW_ESCALATION_DISPATCH_POSTGRES_SMOKE=1 NEX_AG_TEST_DATABASE_URL=postgresql+psycopg://nex_ag_user:***@127.0.0.1:5432/nex_ag_test ./.venv/bin/python scripts/smoke/run_ag_operator_review_escalation_dispatch_postgres_smoke.py --summary`
- `./scripts/quality/run_quality_gate.sh`

## Notes

- The quality gate keeps this smoke opt-in by default, so regular regression
  runs remain fast and deterministic.
- When enabled, the smoke must use the real `nex_ag_test` database and must
  leave no smoke rows behind.
