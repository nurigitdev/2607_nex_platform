# Slice 0479: AG artifact retention history operations projection

Add an AG-owned operations projection over the AE artifact retention execution
history read-model.

## Changes

- Extended `nex_ag.artifact_operations` with
  `ag_artifact_operation_retention_history_projection.v1`.
- Added `AeArtifactOperationsClient.list_artifact_retention_executions(...)` to
  the in-memory and HTTP clients.
- Added `GET /admin/v1/operations/artifact-retention/executions`.
- Added projection, filter, item, source-status, and summary helpers for
  retention execution history operations.

## Decisions

- AE remains the system of record for retention history.
- AG only exposes a metadata-only operator projection and never includes raw
  persisted execution JSON.
- Blocked and failed retention executions are summarized as operator attention
  items.

## Verification

```bash
./.venv/bin/pytest tests/test_nex_ag_artifact_operations.py -q --cov=nex_ag.artifact_operations --cov=nex_ag.main --cov-branch --cov-report=term-missing
```
