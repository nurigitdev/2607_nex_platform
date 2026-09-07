# Slice 0562: AE daemon supervisor command/result contract

## Scope

Add schema-bound AE scheduler daemon supervisor command and result contracts
without starting a process or enabling continuous daemon execution.

## Implementation

- Added `ae_artifact_retention_scheduler_daemon_supervisor_command.v1`.
- Added `ae_artifact_retention_scheduler_daemon_supervisor_result.v1`.
- Supported supervisor actions are `status_probe`, `start_daemon`, and
  `stop_daemon`.
- The first supervisor mode is `fake_dry_run`.
- `start_daemon` requires `test` profile, enabled runtime, and explicit opt-in,
  but the default result remains `BLOCKED` until a supervisor adapter is wired.
- `stop_daemon` defaults to `NOOP` because no supervised process is running in
  this contract-only slice.

## Guardrails

- No process is started or stopped.
- No JobQueue work is enqueued by the supervisor contract.
- No database write is performed by the contract.
- No physical delete automation is enabled.
- AG-safe metadata is preserved; raw execution payloads, storage paths,
  database URLs, and secrets remain out of command/result evidence.

## Evidence

```bash
./.venv/bin/python -m py_compile services/nex-ae-api/nex_ae_api/artifact_retention_scheduler_daemon.py tests/test_nex_ae_artifact_retention_scheduler_daemon_supervisor_contract.py
PYTHONPATH=services/_shared:services/nex-ae-api ./.venv/bin/pytest tests/test_nex_ae_artifact_retention_scheduler_daemon_supervisor_contract.py -q
PYTHONPATH=services/_shared:services/nex-ae-api ./.venv/bin/pytest tests/test_nex_ae_artifact_retention_scheduler_daemon_supervisor_contract.py --cov=nex_ae_api.artifact_retention_scheduler_daemon --cov-branch --cov-report=term-missing
```

## Next

- Slice 0563 adds the injectable fake/dry-run supervisor adapter foundation.
