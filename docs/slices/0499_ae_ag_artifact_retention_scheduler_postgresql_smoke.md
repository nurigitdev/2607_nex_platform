# Slice 0499: AE/AG Artifact Retention Scheduler PostgreSQL Smoke Evidence

## Scope

Add protected PostgreSQL smoke evidence for the S50 scheduled artifact retention
operator path:

- AE remains the system of record for artifact retention scheduler state and
  JobQueue admission.
- AG dispatches through AE's protected scheduled-job admission API.
- AG lists scheduled jobs through AE's protected scheduled-job read-model API.
- The smoke directly verifies the persisted `service_jobs` row in the AE test
  database.

## Smoke Contract

The optional smoke runner is:

```text
scripts/smoke/run_ae_ag_artifact_retention_scheduler_postgres_smoke.py
```

It is skipped by default unless explicitly enabled:

```text
NEX_AE_AG_ARTIFACT_RETENTION_SCHEDULER_POSTGRES_SMOKE=1
NEX_AE_TEST_DATABASE_URL=postgresql+psycopg://...
```

Only the `test` profile is accepted for write smoke execution. The runner
applies AE migrations before executing the smoke.

## Evidence

The smoke creates three logically purged rendered artifacts in temporary
storage, dispatches one scheduled retention job through AG, verifies:

- AE scheduler config is reachable and backed by `SqlAlchemyJobQueue`.
- AG dispatch projection is `READY`, `ENQUEUED`, and `QUEUED`.
- AG scheduled-job projection can read the same queued job.
- The AE test DB contains exactly one matching `service_jobs` row.
- Artifact rows and materialized files are retained.
- Smoke artifacts and queued jobs are cleaned up.

Evidence stays metadata-only and must not include raw database URLs, passwords,
local storage roots, `storage_ref`, `content_base64`, or rendered payloads.
