# Slice 0483: AE artifact retention batch plan read-model

Build the metadata-only batch plan surface that sits between scheduled
retention policy and guarded purge execution.

## Scope

- Added runtime helpers:
  - `AE_ARTIFACT_RETENTION_BATCH_PLAN_SCHEMA_VERSION`
  - `AE_ARTIFACT_RETENTION_BATCH_PLAN_ITEM_SCHEMA_VERSION`
  - `build_artifact_retention_batch_plan(...)`
  - `validate_artifact_retention_batch_plan(...)`
  - `summarize_artifact_retention_batch_plan(...)`
- Added `plan_retention_batch(...)` to in-memory and SQLAlchemy artifact
  stores.
- Added JSON Schema:
  - `contracts/schemas/generation/ae_artifact_retention_batch_plan.v1.schema.json`
- Added positive and negative contract fixtures.
- Added regression coverage for READY and NOOP plans, selection limits,
  estimated delete counts, metadata-only redaction, validation failures, and
  SQLite-backed store planning.

## Decisions

- Batch plans are read-models only; they do not mutate database rows, rendered
  files, or retention history.
- Plans reuse the Slice 0482 schedule contract and keep
  `scheduler_status=DISABLED` until an explicit scheduler/worker is added.
- Candidate selection is bounded by `max_delete_count`, while scan size remains
  bounded by the retention candidate filter limit.
- Plan items expose only metadata required for operator approval and future
  dispatch; raw artifact payloads, rendered content, storage references, and
  database URLs remain excluded.

## Evidence

```bash
./.venv/bin/pytest tests/test_nex_ae_artifacts.py -q --cov=nex_ae_api.artifacts --cov-branch --cov-report=term-missing
./.venv/bin/python scripts/quality/validate_contracts.py
```
