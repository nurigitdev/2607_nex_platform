# Slice 0087: SQLAlchemy JobQueue adapter and PostgreSQL smoke

## Intent

Slice 0087 starts durable JobQueue execution without forcing every regression
test to depend on PostgreSQL. Runtime services can now choose a persistent
SQLAlchemy-backed queue while the default test suite keeps fast SQLite
coverage.

## Runtime Behavior

`nex_runtime.jobs` now provides:

- `SqlAlchemyJobQueue`
- persistent enqueue/get/list/transition over the service-owned `service_jobs`
  table
- idempotent enqueue by `job_type + idempotency_key`
- `claim_next_job(worker_id, job_type=...)` for worker-side claim
- PostgreSQL `FOR UPDATE SKIP LOCKED` claim behavior when the backend is
  PostgreSQL
- SQLite-compatible JSON text fallback for regression tests

Returned jobs remain aligned to `common_job.v1`; database-only columns such as
`payload`, `error`, lock timestamps, and completion timestamps stay internal to
the durable queue table until a later service contract explicitly exposes them.

## PostgreSQL Smoke

The optional smoke script is:

```bash
./.venv/bin/python scripts/smoke/run_postgres_jobqueue_smoke.py --summary
```

Default behavior is skipped. To execute against a local test DB:

```text
NEX_DB_JOBQUEUE_SMOKE=1
NEX_DB_JOBQUEUE_SMOKE_SERVICE=nex-cx
NEX_DB_JOBQUEUE_SMOKE_PROFILE=test
```

The smoke is write-capable but limited to the `test` profile. It applies
service migrations, enqueues one smoke job, verifies idempotent enqueue, claims
the job, completes it, and deletes the smoke row.

## Transaction Rule

Queue operations use short transactions around durable state changes only.
Workers should claim or transition a job in one transaction, perform slow
external work outside the transaction, then open a new transaction to publish
the next durable state.

## Evidence

- Targeted regression:
  `./.venv/bin/pytest tests/test_nex_runtime_jobs.py tests/test_smoke_helpers.py`
- Full quality gate:
  `scripts/quality/run_quality_gate.sh`
