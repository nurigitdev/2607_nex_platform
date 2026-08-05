# Slice 0093: Shared operational event emitter

## Intent

Slice 0093 turns the Slice 0085 operational event store into a small write port
that route and worker code can use directly. The goal is to avoid service code
repeating event construction, redaction, validation, and persistence selection.

## Runtime Behavior

`nex_runtime.operational_events` now exposes:

- `OperationalEventEmitter`
- `OperationalEventEmitResult`
- `operational_event_emitter_from_app`

`OperationalEventEmitter.emit()` builds an `operational_event.v1`, redacts
sensitive details, validates it, appends it to the configured store, and returns
the stored event. It preserves `OperationalEventError` for callers that need
strict behavior.

`OperationalEventEmitter.safe_emit()` returns a compact result instead of
raising for event logging failures. Expected validation and store errors keep
their original error code and status. Unexpected store exceptions are mapped to
`operational_event.emit_failed` with a generic 503 detail so event logging cannot
leak implementation details or fail the primary request path.

`operational_event_emitter_from_app()` resolves the store in this order:

1. explicit store override
2. `app.state.nex_persistence.operational_event_store`
3. per-app in-memory fallback store
4. private in-memory store for stateless helpers

## Testing Boundary

This slice keeps SQLite/memory regression as the default. It does not add a new
PostgreSQL smoke because Slice 0088 already validates the SQLAlchemy
OperationalEventStore write path and Slice 0091 attaches that store through
runtime persistence.

## Evidence

- Targeted regression:
  `./.venv/bin/pytest tests/test_nex_runtime_operational_events.py`
- Full quality gate:
  `scripts/quality/run_quality_gate.sh`
