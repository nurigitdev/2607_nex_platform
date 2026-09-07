# Slice 0564: AE daemon supervisor persistence foundation

## Scope

Persist AE scheduler daemon supervisor command/result outcomes and a matching
operational event in AE-owned storage.

## Implementation

- Added `SqlAlchemyArtifactRetentionSchedulerDaemonSupervisorStore`.
- Added safe supervisor result record/event builders and validators.
- Added SQLite/PostgreSQL-compatible runtime schema creation for supervisor
  result and event tables.
- Added PostgreSQL migration
  `database/nex-ae-api/migrations/0564_ae_artifact_retention_scheduler_daemon_supervisor_persistence.sql`.
- Added regression coverage for upsert, read filters, event lookup, cascade
  cleanup, validation edges, and store-unavailable behavior.

## Guardrails

- Persistence remains AE-owned.
- Supervisor records/events are safe for AG projection.
- Persisted records keep indexed summary columns for `scheduler_id`, `action`,
  `result_status`, and observed time.
- Process start/stop side effects remain disabled in this slice.
- JobQueue admission, worker execution, and physical delete automation remain
  disabled.
- Database URLs, storage paths, raw artifact payloads, raw runtime payloads, and
  secrets are excluded from persisted evidence.

## Evidence

```bash
./.venv/bin/python -m py_compile services/nex-ae-api/nex_ae_api/artifact_retention_scheduler_daemon.py tests/test_nex_ae_artifact_retention_scheduler_daemon_supervisor_persistence.py
PYTHONPATH=services/_shared:services/nex-ae-api ./.venv/bin/pytest tests/test_nex_ae_artifact_retention_scheduler_daemon_cli_execution.py tests/test_nex_ae_artifact_retention_scheduler_daemon_supervisor_contract.py tests/test_nex_ae_artifact_retention_scheduler_daemon_supervisor_persistence.py -q --cov=nex_ae_api.artifact_retention_scheduler_daemon --cov-branch --cov-report=term-missing
```

Result: `26 passed`, daemon module branch-aware coverage `85%`.

## Next

- Slice 0565 wires AE supervisor control/read APIs to the persistence store.
