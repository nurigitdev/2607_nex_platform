# Slice 0555: AE daemon bounded-loop CLI execution wiring

## Scope

Wire the AE artifact retention scheduler daemon execute command to the existing
finite bounded-loop runner without making executable daemon runtime the default.

## Decisions

- The default CLI path remains plan-only.
- `--execute` is available only through an injected execution context in tests
  and service wiring; a bare CLI execute request fails before any work starts.
- Execution still requires the `test` profile, `enabled=true`,
  `explicit_opt_in=true`, and bounded `max_cycles`.
- The new `ae_artifact_retention_scheduler_daemon_cli_execution_result.v1`
  envelope binds execute command, pid/process metadata, started/completed run
  metadata, optional shutdown-signal adapter evidence, and the existing
  bounded-loop result.
- The bounded-loop runner is reused directly. Retention work still enters
  finite JobQueue jobs, while daemon run record persistence remains deferred to
  Slice 0557.
- The execution result includes no database URL, storage path, raw artifact
  payload, raw execution payload, or secret.

## Evidence

- `services/nex-ae-api/nex_ae_api/artifact_retention_scheduler_daemon.py`
- `tests/test_nex_ae_artifact_retention_scheduler_daemon_cli_execution.py`
- `./.venv/bin/pytest tests/test_nex_ae_artifact_retention_scheduler_daemon_cli_execution.py -q`
- `PYTHONPATH=services/_shared:services/nex-ae-api ./.venv/bin/pytest tests/test_nex_ae_artifact_retention_scheduler_daemon.py tests/test_nex_ae_artifact_retention_scheduler_daemon_process_metadata.py tests/test_nex_ae_artifact_retention_scheduler_daemon_signal_adapter.py tests/test_nex_ae_artifact_retention_scheduler_daemon_cli_execution.py --cov=nex_ae_api.artifact_retention_scheduler_daemon --cov-branch --cov-report=term-missing -q`

## Next

- Slice 0556 proves this execution wiring against the real AE PostgreSQL test
  database with protected opt-in and cleanup.
