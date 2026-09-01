# Slice 0466: AE artifact retention execution contract/schema

## Scope

Freeze the AE artifact retention execution evidence before adding store or API
purge capability.

## Changes

- Added `ae_artifact_retention_execution.v1` JSON Schema.
- Added dry-run planned and guarded execute-succeeded contract examples.
- Added a negative contract example for `DRY_RUN` with delete flags enabled.
- Added runtime builder/validator helpers in `nex_ae_api.artifacts`.
- Added regression coverage for dry-run defaults, blocked execute, guarded
  execute, count validation, redaction, audit validation, and delete limits.

## Decisions

- Physical purge remains a guarded batch capability, not a normal lifecycle
  action.
- Logical purge must happen first through `artifact_status=DELETED`.
- `DRY_RUN` cannot enable database or storage mutation flags.
- `EXECUTE/SUCCEEDED` requires all three flags:
  `delete_enabled`, `storage_mutation_enabled`, and
  `database_row_delete_enabled`.
- The first batch window remains 02:00-05:00 `Asia/Seoul`.
- Default delete batch size is 20 artifacts and the initial hard limit is 100.

## Evidence

```bash
./.venv/bin/pytest tests/test_nex_ae_artifacts.py -q --cov=nex_ae_api.artifacts --cov-branch --cov-report=term-missing
./.venv/bin/python scripts/quality/validate_contracts.py
```
