# Slice 0092: CX processing PostgreSQL JobQueue runtime smoke

## Intent

Slice 0092 proves that the Slice 0091 runtime persistence switch is not only
constructed, but also used by a real CX route. When enabled, the CX document
processing route runs with a PostgreSQL-backed `SqlAlchemyJobQueue` and writes
the processing lifecycle to `service_jobs`.

## Runtime Behavior

The new guarded smoke runner is:

```bash
./.venv/bin/python scripts/smoke/run_cx_processing_postgres_jobqueue_smoke.py --summary
```

Default behavior is skipped. To execute against the CX test database:

```text
NEX_CX_PROCESSING_POSTGRES_JOBQUEUE_SMOKE=1
NEX_CX_PROCESSING_POSTGRES_JOBQUEUE_SMOKE_PROFILE=test
NEX_CX_TEST_DATABASE_URL=postgresql://...
```

The smoke is limited to the `test` profile. It:

- applies CX service migrations
- builds a CX FastAPI app with `NEX_CX_PERSISTENCE_MODE=postgres`
- registers ingestion and processing routes
- uploads a small text document through the route
- runs `/api/v1/documents/{document_id}/processing/run`
- reads `service_jobs` to confirm the stored processing job reached
  `SUCCEEDED`
- deletes the smoke job row afterwards

## Testing Boundary

SQLite regression remains the default for fast adapter behavior. This smoke is
the route-level PostgreSQL evidence that the runtime bootstrap and CX processing
JobQueue wiring agree.

## Evidence

- SQLite-style regression:
  `./.venv/bin/pytest tests/test_smoke_helpers.py`
- Default skipped smoke:
  `./.venv/bin/python scripts/smoke/run_cx_processing_postgres_jobqueue_smoke.py --summary`
- PostgreSQL route smoke:
  `NEX_CX_PROCESSING_POSTGRES_JOBQUEUE_SMOKE=1 ... ./.venv/bin/python scripts/smoke/run_cx_processing_postgres_jobqueue_smoke.py --summary`
- Full quality gate:
  `scripts/quality/run_quality_gate.sh`
