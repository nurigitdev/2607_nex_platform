# Slice 0095: CX processing PostgreSQL OperationalEvent smoke

## Intent

Slice 0095 proves that the CX processing lifecycle events added in Slice 0094
can be written through the real service runtime into PostgreSQL-backed
`service_operational_events`.

## Runtime Behavior

The new guarded smoke runner is:

```bash
./.venv/bin/python scripts/smoke/run_cx_processing_postgres_event_smoke.py --summary
```

Default behavior is skipped. To execute against the CX test database:

```text
NEX_CX_PROCESSING_POSTGRES_EVENT_SMOKE=1
NEX_CX_PROCESSING_POSTGRES_EVENT_SMOKE_PROFILE=test
NEX_CX_TEST_DATABASE_URL=postgresql://...
```

The smoke is limited to the `test` profile. It:

- applies CX service migrations
- builds a CX FastAPI app with `NEX_CX_PERSISTENCE_MODE=postgres`
- registers ingestion and processing routes
- uploads a small text document through the route
- runs `/api/v1/documents/{document_id}/processing/run`
- reads `service_operational_events` to confirm durable
  `cx.processing.started` and `cx.processing.succeeded` rows
- confirms no `cx.processing.failed` row appears for the successful run
- checks deterministic event IDs, subject `cx.document`, and redaction-safe
  details
- deletes smoke job/event rows afterwards

## Testing Boundary

SQLite regression remains the default for fast script behavior and branch
coverage. The guarded PostgreSQL smoke is the route-level evidence that the
runtime OperationalEventStore is actually used by CX processing in PostgreSQL
mode.

## Evidence

- SQLite-style regression:
  `./.venv/bin/pytest tests/test_smoke_helpers.py`
- Default skipped smoke:
  `./.venv/bin/python scripts/smoke/run_cx_processing_postgres_event_smoke.py --summary`
- PostgreSQL route smoke:
  `NEX_CX_PROCESSING_POSTGRES_EVENT_SMOKE=1 ... ./.venv/bin/python scripts/smoke/run_cx_processing_postgres_event_smoke.py --summary`
- Full quality gate:
  `scripts/quality/run_quality_gate.sh`
