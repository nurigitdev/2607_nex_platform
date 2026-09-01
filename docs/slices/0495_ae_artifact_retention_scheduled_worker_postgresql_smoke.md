# Slice 0495: AE artifact retention scheduled worker PostgreSQL smoke

Prove the S50 scheduled retention JobQueue and worker adapter path against the
real AE test database when explicitly enabled.

## Scope

- Added `scripts/smoke/run_ae_artifact_retention_scheduled_worker_postgres_smoke.py`.
- The smoke migrates `NEX_AE_TEST_DATABASE_URL`, creates rendered deleted
  artifacts, builds a READY batch plan, enqueues the scheduled retention job,
  runs the shared worker once, and directly observes `service_jobs`,
  `service_worker_heartbeats`, and `ae_artifact_retention_executions`.
- Added SQLite-backed regression coverage for skip/fail/pass paths, redaction,
  helper branches, and quality-gate behavior.

## Decisions

- 0495 remains opt-in and is skipped in the default quality gate until
  `NEX_AE_ARTIFACT_RETENTION_SCHEDULED_WORKER_POSTGRES_SMOKE=1` is set.
- The smoke is restricted to the `test` profile and must use
  `NEX_AE_TEST_DATABASE_URL`.
- The worker still performs dry-run retention only; physical delete automation
  remains deferred beyond S50.

## Evidence

```bash
./.venv/bin/pytest tests/test_ae_artifact_retention_scheduled_worker_postgres_smoke.py -q --cov=run_ae_artifact_retention_scheduled_worker_postgres_smoke --cov-branch --cov-report=term-missing
NEX_AE_ARTIFACT_RETENTION_SCHEDULED_WORKER_POSTGRES_SMOKE=1 NEX_AE_TEST_DATABASE_URL='<ae-test-database-url>' ./.venv/bin/python scripts/smoke/run_ae_artifact_retention_scheduled_worker_postgres_smoke.py --summary
```
