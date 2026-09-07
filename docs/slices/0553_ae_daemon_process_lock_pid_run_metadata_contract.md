# Slice 0553: AE daemon process lock / pid / run metadata contract

## Scope

Define safe process lock, pid, and daemon run metadata contracts for the AE
artifact retention scheduler daemon before actual CLI execution or persistence
wiring.

## Decisions

- The process lock contract records scheduler scope, execute command id, host
  id, pid, lock owner, stale window, and command summary.
- The run metadata contract records the execute command id, process lock id,
  process identity, command summary, and lifecycle timestamps.
- `lock_owner` is deterministic: `scheduler_id:host_id:process_id`.
- Run lifecycle timestamps are status-bound: `PENDING` has no start/end,
  `RUNNING` and `STOPPING` require a start without completion, and terminal
  statuses require both start and completion timestamps.
- These contracts are metadata-only. They do not acquire a lock, write the
  database, enqueue JobQueue work, execute workers, persist runtime state, or
  enable physical delete automation.

## Evidence

- `services/nex-ae-api/nex_ae_api/artifact_retention_scheduler_daemon.py`
- `tests/test_nex_ae_artifact_retention_scheduler_daemon_process_metadata.py`
- `./.venv/bin/pytest tests/test_nex_ae_artifact_retention_scheduler_daemon.py tests/test_nex_ae_artifact_retention_scheduler_daemon_process_metadata.py -q`

## Next

- Slice 0554 adds graceful shutdown signal adapter contracts before the CLI
  bounded-loop execution wiring.
