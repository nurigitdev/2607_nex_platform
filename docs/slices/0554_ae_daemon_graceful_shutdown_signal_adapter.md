# Slice 0554: AE daemon graceful shutdown signal adapter

## Scope

Add a metadata-only signal shutdown adapter for the AE artifact retention
scheduler daemon before installing real process signal handlers.

## Decisions

- Supported shutdown signals are `SIGTERM` and `SIGINT`.
- The adapter binds the current daemon runtime state, process lock metadata, run
  metadata, and the existing graceful shutdown transition contract.
- Signal names are normalized to uppercase and projected through
  `build_artifact_retention_scheduler_daemon_shutdown_transition`.
- The adapter can produce READY shutdown evidence for `STARTING`/`RUNNING`
  states and NOOP evidence for disabled or already non-running states.
- The adapter does not install signal handlers, deliver process signals,
  terminate processes, write the database, enqueue JobQueue work, execute
  workers, persist runtime state, or enable physical delete automation.

## Evidence

- `services/nex-ae-api/nex_ae_api/artifact_retention_scheduler_daemon.py`
- `tests/test_nex_ae_artifact_retention_scheduler_daemon_signal_adapter.py`
- `./.venv/bin/pytest tests/test_nex_ae_artifact_retention_scheduler_daemon.py tests/test_nex_ae_artifact_retention_scheduler_daemon_process_metadata.py tests/test_nex_ae_artifact_retention_scheduler_daemon_signal_adapter.py -q`

## Next

- Slice 0555 wires protected bounded-loop CLI execution using these command,
  process metadata, and shutdown adapter contracts.
