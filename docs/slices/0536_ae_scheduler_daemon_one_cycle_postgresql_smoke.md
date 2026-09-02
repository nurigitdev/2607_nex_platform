# Slice 0536: AE Scheduler Daemon One-Cycle PostgreSQL Smoke

## Scope

Add protected PostgreSQL smoke evidence for the AE scheduler daemon one-cycle
runner. This complements the existing daemon control-route smoke by executing
`run_artifact_retention_scheduler_daemon_one_cycle` directly against
SQLAlchemy-backed AE test persistence.

## Behavior

- The smoke is opt-in through
  `NEX_AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_ONE_CYCLE_POSTGRES_SMOKE=1`.
- Only the `test` profile is accepted for write execution.
- The runner migrates the AE test database before execution.
- The smoke seeds deleted artifact rows, runs a one-cycle daemon pass with
  explicit test-profile opt-in, and reads back lease, JobQueue, worker, and
  retention-history state.
- The one-cycle path remains single-pass only and still starts no daemon process
  or continuous loop.

## Guardrails

- The default quality gate invokes the smoke runner, but it skips until
  explicitly enabled.
- Evidence redacts database URLs, database passwords, storage roots, raw
  artifact payloads, rendered payloads, and local data paths.
- Physical delete automation remains disabled and all smoke rows are cleaned up.

## Evidence

```bash
./.venv/bin/pytest tests/test_ae_artifact_retention_scheduler_daemon_one_cycle_postgres_smoke.py --cov=run_ae_artifact_retention_scheduler_daemon_one_cycle_postgres_smoke --cov-branch --cov-report=term-missing
NEX_AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_ONE_CYCLE_POSTGRES_SMOKE=1 \
  NEX_AE_TEST_DATABASE_URL=<redacted AE test database URL> \
  ./.venv/bin/python scripts/smoke/run_ae_artifact_retention_scheduler_daemon_one_cycle_postgres_smoke.py --summary
```
