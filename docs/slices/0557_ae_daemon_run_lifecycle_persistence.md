# Slice 0557: AE daemon run/lifecycle persistence

## Scope

Persist safe AE scheduler daemon CLI execution run records and lifecycle event
summaries after the bounded-loop execution path succeeds.

## Decisions

- AE owns the new persistence tables:
  `ae_artifact_retention_scheduler_daemon_runs` and
  `ae_artifact_retention_scheduler_daemon_lifecycle_events`.
- The store writes only safe projections plus a payload hash. It does not store
  raw CLI execution payloads, database URLs, storage paths, storage refs,
  base64 content, or rendered artifact payloads.
- `run_store` is optional. Without it, Slice 0555 metadata-only behavior remains
  unchanged. With it, CLI execution result guardrails/metadata report
  `run_record_persisted=true` and `lifecycle_event_persisted=true`.
- The existing process lock/run metadata contracts remain metadata-only:
  process lock acquisition and continuous runtime-state persistence are still
  separate future concerns.
- The protected PostgreSQL smoke now verifies one daemon run row and two
  lifecycle event rows (`RUN_STARTED`, `RUN_COMPLETED`) against the real AE test
  database, then deletes the rows during cleanup.

## Evidence

- `database/nex-ae-api/migrations/0557_ae_artifact_retention_scheduler_daemon_run_persistence.sql`
- `services/nex-ae-api/nex_ae_api/artifact_retention_scheduler_daemon.py`
- `tests/test_nex_ae_artifact_retention_scheduler_daemon_cli_execution.py`
- `tests/test_ae_artifact_retention_scheduler_daemon_cli_execution_postgres_smoke.py`
- `./.venv/bin/pytest tests/test_nex_ae_artifact_retention_scheduler_daemon_cli_execution.py -q`
- `./.venv/bin/pytest tests/test_ae_artifact_retention_scheduler_daemon_cli_execution_postgres_smoke.py -q`
- `NEX_AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_CLI_EXECUTION_POSTGRES_SMOKE=1 NEX_AE_TEST_DATABASE_URL=<test-db-url> ./.venv/bin/python scripts/smoke/run_ae_artifact_retention_scheduler_daemon_cli_execution_postgres_smoke.py --summary`

## Next

- Later S56 slices can expose a read-only AE route or AG projection over these
  persisted run/event summaries without granting AG write access.
