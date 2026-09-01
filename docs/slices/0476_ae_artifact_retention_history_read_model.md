# Slice 0476: AE artifact retention history read-model

Expose a metadata-only collection contract for artifact retention execution
history before adding an HTTP query route.

## Changes

- Added `ae_artifact_retention_execution_history_collection.v1`.
- Added `ae_artifact_retention_execution_history_item.v1`.
- Added public filter, item, collection, summary, and redaction helpers for
  retention execution history.
- Kept the persisted `ae_artifact_retention_execution_history.v1` record as the
  internal source of truth while omitting raw execution payloads from list items.

## Decisions

- Retention history collection responses are metadata-only and include payload
  hashes instead of full persisted execution JSON.
- The collection summary reports mode/status counts, blocked/failed counts,
  deleted artifact totals, deleted storage-file totals, and latest check time.
- Store contracts remain unchanged; stores still return persisted history records
  and API/projection layers wrap them into safe read-models.

## Verification

```bash
./.venv/bin/pytest tests/test_nex_ae_artifacts.py -q --cov=nex_ae_api.artifacts --cov-branch --cov-report=term-missing
```
