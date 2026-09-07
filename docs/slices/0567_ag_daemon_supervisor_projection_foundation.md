# Slice 0567: AG daemon supervisor projection foundation

## Scope

Add the AG read-only projection foundation for AE scheduler daemon supervisor
results.

## Implementation

- Extended the AG AE artifact operations client protocol with supervisor result
  collection and detail read methods.
- Added in-memory and HTTP client adapters for:
  - `/api/v1/artifact-retention/scheduler-daemon-supervisor-results`
  - `/api/v1/artifact-retention/scheduler-daemon-supervisor-results/{id}`
- Added AG projection builders for supervisor collection and detail read models.
- Added supervisor action/result normalizers, source status summaries, cache
  keys, and empty fallback payloads.
- Added strict projection allow-lists for supervisor record/event summaries and
  metadata.

## Guardrails

- AG remains read-only and metadata-only.
- AE remains the system of record for supervisor persistence, JobQueue
  admission, and daemon process control.
- Supervisor command/result raw payloads, database URLs, local storage paths,
  raw artifact payloads, and raw execution payloads are not included in AG
  projections.
- No AG route is opened in this slice; route wiring should happen in a later
  slice after the projection surface is stable.

## Evidence

```bash
./.venv/bin/python -m py_compile services/nex-ag/nex_ag/artifact_operations.py tests/test_nex_ag_artifact_operations.py
PYTHONPATH=services/_shared:services/nex-ag ./.venv/bin/pytest tests/test_nex_ag_artifact_operations.py -q --cov=nex_ag.artifact_operations --cov-branch --cov-report=term-missing
```

Results:

- Targeted AG artifact operations regression: `71 passed`.
- `nex_ag.artifact_operations` targeted coverage: `98%`.

## Next

- Slice 0568 should wire the AG admin read-only route for supervisor result
  collection/detail projections.
