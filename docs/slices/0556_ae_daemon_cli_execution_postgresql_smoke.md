# Slice 0556: AE daemon CLI execution PostgreSQL smoke

## Scope

Prove the Slice 0555 CLI `--execute` path against the real AE PostgreSQL test
database while keeping the default quality gate protected and non-writing.

## Decisions

- The new smoke is opt-in only:
  `NEX_AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_CLI_EXECUTION_POSTGRES_SMOKE=1`.
- Write execution is still restricted to the `test` profile and
  `NEX_AE_TEST_DATABASE_URL`.
- The smoke calls the CLI `main(..., execution_context=...)` path instead of a
  bare process spawn so the dependency-injection boundary from Slice 0555 stays
  explicit.
- It seeds deleted artifacts, runs two bounded-loop cycles with worker execution
  enabled, reads back JobQueue, lease, daemon heartbeat, scheduler-runtime, and
  retention-history rows, and then removes all seeded rows.
- Evidence includes only redacted metadata: no raw database URL, storage path,
  storage ref, base64 content, rendered payloads, or local data path.
- Daemon run record and lifecycle event persistence are still deferred to Slice
  0557.

## Evidence

- `scripts/smoke/run_ae_artifact_retention_scheduler_daemon_cli_execution_postgres_smoke.py`
- `tests/test_ae_artifact_retention_scheduler_daemon_cli_execution_postgres_smoke.py`
- `./.venv/bin/pytest tests/test_ae_artifact_retention_scheduler_daemon_cli_execution_postgres_smoke.py -q`
- `NEX_AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_CLI_EXECUTION_POSTGRES_SMOKE=1 NEX_AE_TEST_DATABASE_URL=<test-db-url> ./.venv/bin/python scripts/smoke/run_ae_artifact_retention_scheduler_daemon_cli_execution_postgres_smoke.py --summary`

## Next

- Slice 0557 persists safe daemon run records and lifecycle event summaries,
  replacing the current metadata-only `run_record_persisted=false` evidence.
