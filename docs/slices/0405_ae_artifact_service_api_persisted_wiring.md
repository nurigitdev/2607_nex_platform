# Slice 0405: AE Artifact Service API Persisted Wiring

## Scope

Wire AE artifact routes to the SQLAlchemy artifact stores whenever the service
app has an attached persistence runtime.

## Decisions

- Explicit route test stores still override defaults, preserving deterministic
  mock-first regression behavior.
- `build_default_artifact_handoff_store(app)` and
  `build_default_artifact_record_store(app)` select SQLAlchemy stores from
  `app.state.nex_persistence.api_session_factory`.
- When `NEX_AE_ARTIFACT_STORAGE_ROOT` is configured, the default artifact record
  store uses the local rendered payload adapter. Otherwise it keeps the
  in-memory payload adapter for local mock runs.
- The API response contract is unchanged: create, read, render-job, preview, and
  download routes still expose safe artifact records and logical storage refs.

## Evidence

- `./.venv/bin/pytest tests/test_nex_ae_artifacts.py -q --cov=nex_ae_api.artifacts --cov-branch --cov-report=term-missing`
  - `43 passed, 1 warning`
  - `services/nex-ae-api/nex_ae_api/artifacts.py` coverage `96%`
