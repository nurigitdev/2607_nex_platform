# Slice 0549: AG scheduler daemon lifecycle PostgreSQL smoke evidence

## Scope

Harden the protected AE/AG scheduler daemon PostgreSQL smoke so it proves AG can
project lifecycle evidence from AE test persistence.

## Implementation

- `run_ae_ag_artifact_retention_scheduler_daemon_postgres_smoke.py` now writes a
  scheduler daemon heartbeat through the DB-backed `SqlAlchemyWorkerHeartbeatStore`
  before AG calls the AE daemon runtime route.
- The smoke verifies both AG daemon config and AG manual tick routes expose
  `RUNNING` lifecycle projection from the persisted heartbeat.
- Checks now cover lifecycle summary fields, nested `lifecycle_projection`
  attention, actual daemon heartbeat persistence, and cleanup of the daemon
  heartbeat row.
- The summary line includes `lifecycle=RUNNING` so operator evidence is visible
  without printing raw JSON.

## Guardrails

- The smoke still requires explicit opt-in and a test database URL.
- Migration and execution remain blocked for non-test profiles.
- Evidence is redacted for database URLs, database passwords, local storage
  paths, raw artifact payloads, and rendered payloads.
- AG remains read-only: runtime observations come from AE APIs, while all
  persistence writes in the smoke are AE test setup/execution/cleanup.

## Evidence

```bash
./.venv/bin/python -m py_compile scripts/smoke/run_ae_ag_artifact_retention_scheduler_daemon_postgres_smoke.py tests/test_ae_ag_artifact_retention_scheduler_daemon_postgres_smoke.py
./.venv/bin/pytest tests/test_ae_ag_artifact_retention_scheduler_daemon_postgres_smoke.py -q
./.venv/bin/pytest tests/test_ae_ag_artifact_retention_scheduler_daemon_postgres_smoke.py --cov=run_ae_ag_artifact_retention_scheduler_daemon_postgres_smoke --cov-branch --cov-report=term-missing
NEX_AE_AG_ARTIFACT_RETENTION_SCHEDULER_DAEMON_POSTGRES_SMOKE=1 NEX_AE_TEST_DATABASE_URL=<test-db-url> ./.venv/bin/python scripts/smoke/run_ae_ag_artifact_retention_scheduler_daemon_postgres_smoke.py --summary
./scripts/quality/run_quality_gate.sh
```
