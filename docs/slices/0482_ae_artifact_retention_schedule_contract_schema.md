# Slice 0482: AE artifact retention schedule contract/schema

Freeze the scheduled artifact retention policy shape before batch-plan
read-models or worker commands are added.

## Scope

- Added runtime helpers:
  - `AE_ARTIFACT_RETENTION_SCHEDULE_SCHEMA_VERSION`
  - `build_artifact_retention_schedule(...)`
  - `validate_artifact_retention_schedule(...)`
- Added JSON Schema:
  - `contracts/schemas/generation/ae_artifact_retention_schedule.v1.schema.json`
- Added positive and negative contract fixtures.
- Added regression coverage for schedule defaults, guardrails, invalid sections,
  unsafe payloads, and contract validation wiring.

## Decisions

- `schedule_enabled=false` until an actual scheduler daemon is introduced.
- `planning_enabled=true` so operators can inspect a deterministic batch plan.
- `default_mode=DRY_RUN`; execute-mode remains guarded by delete, storage, and
  database-row flags.
- The first schedule uses 30 retention days, 15/30-day presets, and the
  `02:00-05:00` `Asia/Seoul` window.
- AG remains dispatch/projection only and cannot write directly to AE artifact
  tables.

## Evidence

```bash
./.venv/bin/pytest tests/test_nex_ae_artifacts.py -q --cov=nex_ae_api.artifacts --cov-branch --cov-report=term-missing
./.venv/bin/python scripts/quality/validate_contracts.py
```
