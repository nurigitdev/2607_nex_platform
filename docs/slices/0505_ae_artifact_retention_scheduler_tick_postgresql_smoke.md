# Slice 0505: AE Artifact Retention Scheduler Tick PostgreSQL Smoke

## Scope

Slice 0505 adds protected PostgreSQL evidence for the S51 scheduler tick
admission path.

## Behavior

- The smoke migrates `NEX_AE_TEST_DATABASE_URL` before execution.
- It creates logically purged rendered artifacts, reads an AE batch plan and
  scheduler config, builds a READY scheduler tick plan inside the `Asia/Seoul`
  batch window, and enqueues it through `SqlAlchemyJobQueue`.
- It directly selects the matching `service_jobs` row to confirm a single
  QUEUED `scheduler_tick` job with metadata-only payload.
- It lists the same queued job back through AE's scheduled-job read-model route
  and cleans up smoke artifacts and jobs.

## Guardrails

- Default quality gate behavior is skipped until
  `NEX_AE_ARTIFACT_RETENTION_SCHEDULER_TICK_POSTGRES_SMOKE=1` is set.
- Only the `test` profile and `NEX_AE_TEST_DATABASE_URL` are accepted.
- Worker execution, history writes, scheduler daemon startup, and physical
  deletion remain disabled.
- Evidence must not include raw DB URLs, passwords, local storage roots,
  `storage_ref`, `content_base64`, or rendered payloads.

## Evidence

```bash
./.venv/bin/pytest tests/test_ae_artifact_retention_scheduler_tick_postgres_smoke.py -q --cov=run_ae_artifact_retention_scheduler_tick_postgres_smoke --cov-branch --cov-report=term-missing
NEX_AE_ARTIFACT_RETENTION_SCHEDULER_TICK_POSTGRES_SMOKE=1 NEX_AE_TEST_DATABASE_URL='<ae-test-database-url>' ./.venv/bin/python scripts/smoke/run_ae_artifact_retention_scheduler_tick_postgres_smoke.py --summary
```
