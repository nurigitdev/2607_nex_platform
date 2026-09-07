# Slice 0576: AG supervised process projection foundation

## Scope

Add AG's read-only projection foundation for AE supervised scheduler daemon
process snapshot evidence.

## Implementation

- Added AG projection schema versions for supervised process snapshot
  collection and detail read models.
- Extended the AE artifact operations client protocol, in-memory test client,
  and HTTP client with:
  - `list_artifact_retention_scheduler_daemon_process_snapshots`
  - `get_artifact_retention_scheduler_daemon_process_snapshot_detail`
- Added collection/detail projection builders and summary helpers for process
  status counts, running/stale/failed/blocked attention signals, adapter
  requirement counts, and detail event summaries.
- Added safe projection helpers that retain process metadata but exclude raw
  `supervised_process_snapshot` payloads, database URLs, storage paths, raw
  artifact payloads, raw execution payloads, and raw daemon runtime payloads.
- Added in-memory fallback payloads and cache keys so regression tests can run
  without AE or PostgreSQL.

## Guardrails

- AG remains read-only over AE supervised process evidence.
- AE remains the system of record for process snapshot/event persistence.
- AG does not start/stop subprocesses, enqueue AE jobs, write AE persistence,
  or receive raw process/runtime payloads.
- Admin route wiring is intentionally left for the next Slice.

## Evidence

```bash
./.venv/bin/python -m py_compile services/nex-ag/nex_ag/artifact_operations.py tests/test_nex_ag_artifact_operations.py
PYTHONPATH=services/_shared:services/nex-ag ./.venv/bin/pytest tests/test_nex_ag_artifact_operations.py -q --cov=nex_ag.artifact_operations --cov-branch --cov-report=term-missing
```

Targeted AG artifact operations coverage: 75 passed, statement/branch combined
module coverage 97%.

## Next

- Slice 0577 should expose the AG supervised process projection through
  protected read-only admin routes.
