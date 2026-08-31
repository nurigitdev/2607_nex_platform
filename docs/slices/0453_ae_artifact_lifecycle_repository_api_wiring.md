# Slice 0453: AE Artifact Lifecycle Repository/API Wiring

## Scope

Wire the Slice 0452 lifecycle command contract into AE artifact stores and an
authenticated service API route.

## Changes

- Added `apply_artifact_lifecycle_action(...)` as the common status transition
  helper.
- Added `apply_lifecycle_action(...)` to both in-memory and SQLAlchemy artifact
  stores.
- Added `POST /api/v1/artifacts/{artifact_id}/lifecycle-actions`.
- Extended artifact regression coverage for in-memory store, SQLite-backed
  SQLAlchemy store, API success, API auth, missing artifact, stale status, and
  invalid target errors.
- Indexed Slice 0453 in the Slice documentation and AE API notes.

## Decisions

- Lifecycle actions mutate only artifact metadata status and `updated_at`.
- Physical file deletion, storage purge, and object-storage mutation remain out
  of this route.
- The route returns `ae_artifact_lifecycle_action_result.v1` and keeps raw
  comment text out of the response.
- Stale lifecycle commands fail if the artifact status changed after the action
  request was built.

## Evidence

Targeted regression:

```bash
./.venv/bin/pytest tests/test_nex_ae_artifacts.py -q --cov=nex_ae_api.artifacts --cov-branch --cov-report=term-missing
```

Full quality gate:

```bash
./scripts/quality/run_quality_gate.sh
```
