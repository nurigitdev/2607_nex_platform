# Slice 0607: AG worker execution projection foundation

## Scope

Add the AG-side foundation for projecting AE operator-control execution worker
results.

## Decision

- No new database table is introduced in Slice 0607.
- AG remains a client/projection surface. AE remains the system of record for
  operator-control execution state, transition persistence, and worker
  execution.
- AG may call AE's protected worker route, but the AG projection must expose
  only safe metadata, status summaries, and route hints.
- Raw worker command, transition-plan, supervisor-result, storage, and
  persistence endpoint payloads must not appear in AG projections.

## Implementation

- Added the AG worker projection schema version
  `ag_artifact_operation_retention_daemon_operator_control_execution_worker_projection.v1`.
- Extended the AE artifact operations client contract, in-memory client, and
  HTTP client with a worker-result call to
  `/api/v1/artifact-retention/scheduler-daemon-operator-control-execution-workers`.
- Added a redacted worker-result projection builder and summary helper.
- Added safe metadata/guardrail helpers that normalize sensitive source flags
  into AG-safe field names.
- Added an in-memory fallback worker result for mock/test profiles when a
  worker result is not pre-seeded.

## Guardrails

- AG does not create AE worker commands.
- AG does not persist AE execution transitions.
- AG does not enqueue AE JobQueue work.
- AG does not start or stop AE subprocesses.
- AG does not expose raw worker command, transition-plan, supervisor-result,
  database endpoint, or storage locator payloads.

## Evidence

```bash
./.venv/bin/python -m py_compile services/nex-ag/nex_ag/artifact_operations.py tests/test_nex_ag_artifact_operations.py
./.venv/bin/pytest tests/test_nex_ag_artifact_operations.py -q
```

- Targeted AG regression: `95 passed`.

## Next

- Slice 0608 should wire a protected AG admin route/dashboard surface for this
  worker projection.
