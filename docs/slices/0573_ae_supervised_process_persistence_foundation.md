# Slice 0573: AE supervised process persistence foundation

## Scope

Persist AE supervised daemon process snapshot evidence in AE-owned storage
without enabling any real subprocess start or stop path.

## Implementation

- Added supervised process record/event schema versions.
- Added
  `SqlAlchemyArtifactRetentionSchedulerDaemonSupervisedProcessStore`.
- Added schema creation for
  `ae_artifact_retention_scheduler_daemon_process_snapshots` and
  `ae_artifact_retention_scheduler_daemon_process_events`.
- Added indexed columns for scheduler id, action, process status, host id,
  process id, and observed timestamps.
- Added record/event builders, validators, row adapters, upsert SQL, list/get
  filters, and delete cleanup helpers.
- Added SQLite regression coverage for schema creation, idempotent upsert,
  list filters, event readback, validation edges, and store-unavailable error
  mapping.

## Guardrails

- Slice 0573 does not start or stop a subprocess.
- Persistence is AE-owned; AG remains read-only and must later observe only via
  AE APIs.
- Stored payloads keep only safe snapshot metadata and hashes.
- Database URLs, local storage paths, raw artifact payloads, raw execution
  payloads, raw daemon runtime payloads, provider secrets, and service tokens
  are not stored or projected.
- JobQueue admission and physical delete automation remain disabled for this
  process evidence path.

## Evidence

```bash
./.venv/bin/python -m py_compile services/nex-ae-api/nex_ae_api/artifact_retention_scheduler_daemon.py tests/test_nex_ae_artifact_retention_scheduler_daemon_supervised_process_persistence.py
PYTHONPATH=services/_shared:services/nex-ae-api ./.venv/bin/pytest tests/test_nex_ae_artifact_retention_scheduler_daemon_supervised_process_persistence.py -q --cov=nex_ae_api.artifact_retention_scheduler_daemon --cov-branch --cov-report=term-missing
```

## Next

- Slice 0574 should wire AE service APIs for supervised process dispatch/read
  evidence while keeping process control disabled until the guarded subprocess
  adapter Slice.
