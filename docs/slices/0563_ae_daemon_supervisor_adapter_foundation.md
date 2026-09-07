# Slice 0563: AE daemon supervisor adapter foundation

## Scope

Add the first injectable AE scheduler daemon supervisor adapter foundation while
keeping daemon process start/stop side effects disabled.

## Implementation

- Added `ArtifactRetentionSchedulerDaemonSupervisorAdapter` as the AE-owned
  adapter protocol.
- Added `FakeArtifactRetentionSchedulerDaemonSupervisorAdapter`.
- Added `run_artifact_retention_scheduler_daemon_supervisor_command(...)` as the
  side-effect boundary for supervisor command execution.
- Extended supervisor result evidence with adapter availability, invocation, and
  adapter name metadata.

## Guardrails

- The fake adapter never starts or stops an OS process.
- The fake adapter never delegates CLI bounded-loop execution.
- The fake adapter never enqueues JobQueue work or writes a database row.
- `start_daemon` remains `BLOCKED` in fake/dry-run mode.
- `stop_daemon` remains `NOOP` when no supervised process is running.
- Result evidence remains redacted and AG-safe.

## Evidence

```bash
./.venv/bin/python -m py_compile services/nex-ae-api/nex_ae_api/artifact_retention_scheduler_daemon.py tests/test_nex_ae_artifact_retention_scheduler_daemon_supervisor_contract.py
PYTHONPATH=services/_shared:services/nex-ae-api ./.venv/bin/pytest tests/test_nex_ae_artifact_retention_scheduler_daemon_supervisor_contract.py -q
PYTHONPATH=services/_shared:services/nex-ae-api ./.venv/bin/pytest tests/test_nex_ae_artifact_retention_scheduler_daemon.py tests/test_nex_ae_artifact_retention_scheduler_daemon_cli_execution.py tests/test_nex_ae_artifact_retention_scheduler_daemon_supervisor_contract.py --cov=nex_ae_api.artifact_retention_scheduler_daemon --cov-branch --cov-report=term-missing -q
```

## Next

- Slice 0564 persists supervisor command/result state and emits safe
  operational events in AE-owned storage.
