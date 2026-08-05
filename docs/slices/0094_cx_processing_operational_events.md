# Slice 0094: CX processing operational events

## Intent

Slice 0094 connects the CX document processing pipeline to the shared
operational event emitter from Slice 0093. Operators and AG projections can now
observe processing lifecycle state without scraping route responses or reading
raw document content.

## Runtime Behavior

The processing pipeline emits these event types:

- `cx.processing.started`
- `cx.processing.succeeded`
- `cx.processing.failed`

Events are scoped to subject `cx.document` and carry the request/trace IDs from
the incoming call. Event IDs are deterministic per `pipeline_run_id + event_type`
so repeated storage attempts remain idempotent.

Event details are deliberately small and redaction-safe:

- `pipeline_run_id`
- `job_id`
- `job_status`
- `step_summary` for terminal states
- `failed_step` for failed states

Details do not include raw source text, extracted Markdown, summaries, prompt
text, embeddings, provider endpoints, or API keys.

## Failure Isolation

Processing uses `OperationalEventEmitter.safe_emit()`. Operational event
validation or store failures are reported through the emit result and ignored by
the primary pipeline path, so a temporary observability store outage does not
fail document processing.

## Persistence Boundary

Route registration resolves the event store from
`app.state.nex_persistence.operational_event_store` when available. This keeps
default regression tests in memory and lets PostgreSQL mode write to the
service-owned `service_operational_events` table through the Slice 0091 runtime
bootstrap.

No additional PostgreSQL smoke was added in this slice. Slice 0088 proves the
SQLAlchemy event store write path, Slice 0091 attaches it to service runtime,
and Slice 0092 proves the CX processing route uses runtime persistence for the
JobQueue. This slice adds route/pipeline event wiring regression in memory.

## Evidence

- Targeted regression:
  `./.venv/bin/pytest tests/test_nex_cx_processing.py`
- Full quality gate:
  `scripts/quality/run_quality_gate.sh`
