# Slice 0403: AE Artifact SQLAlchemy Repository + SQLite Regression

## Scope

Add SQLAlchemy repository adapters for the AE artifact handoff and artifact
record family while keeping the default API runtime on the existing in-memory
stores until route wiring is switched in a later slice.

## Decisions

- `SqlAlchemyArtifactHandoffStore` persists validated handoff records into
  `ae_artifact_handoffs` and exposes the same `save/get/delete` shape as the
  in-memory store.
- `SqlAlchemyArtifactRecordStore` persists artifact records plus source refs,
  versions, render jobs, files, and links into the Slice 0402 table family.
- Rendered Markdown payloads remain process-local inside the SQLAlchemy store
  for this slice. Durable payload storage is still deferred to Slice 0404.
- SQLite regression uses the same repository methods with JSON stored as text,
  while PostgreSQL will store those fields as JSONB through dialect-aware casts.

## Evidence

- `./.venv/bin/pytest tests/test_nex_ae_artifacts.py -q --cov=nex_ae_api.artifacts --cov-branch --cov-report=term-missing`
  - `32 passed, 1 warning`
  - `services/nex-ae-api/nex_ae_api/artifacts.py` coverage `96%`
