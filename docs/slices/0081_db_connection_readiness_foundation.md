# Slice 0081: DB connection readiness foundation

## Intent

Slice 0081 starts the database-connected platform phase without committing local
secrets. It centralizes service database URL lookup, redaction, readiness checks,
and SQLAlchemy session construction in the shared runtime package.

## Runtime Behavior

- `/ready` now checks the configured service database through
  `nex_runtime.database.check_database_readiness`.
- Readiness failures distinguish missing env, placeholder env, and connection
  failure.
- Successful readiness records include `current_database()` and `current_user`
  evidence, never the raw database URL.
- `required_database_url` rejects placeholder passwords so `.env.example`
  values cannot accidentally be used as live configuration.
- `build_engine` and `build_session_factory` provide the shared SQLAlchemy
  entrypoint for later repositories and service transactions.

## Vector Database Option

CX now has an optional vector database override:

```text
NEX_CX_VECTOR_DATABASE_URL
NEX_CX_VECTOR_TEST_DATABASE_URL
```

When the override is empty, CX vector data uses the primary CX database. This
keeps the MVP simple while preserving a clean path to split vector storage later.

## Evidence

- Targeted regression:
  `./.venv/bin/pytest tests/test_nex_runtime_database.py tests/test_nex_runtime_app.py tests/test_smoke_helpers.py`
- Full quality gate:
  `scripts/quality/run_quality_gate.sh`
