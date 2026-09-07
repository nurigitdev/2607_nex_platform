# Slice 0575: AE supervised process PostgreSQL smoke evidence

## Scope

Add protected PostgreSQL smoke evidence for the AE supervised daemon process
snapshot API path.

## Implementation

- Added the PostgreSQL migration
  `0575_ae_artifact_retention_scheduler_daemon_supervised_process_persistence`.
- Added
  `scripts/smoke/run_ae_artifact_retention_scheduler_daemon_supervised_process_postgres_smoke.py`.
- Added the optional quality-gate hook. The smoke remains skipped unless
  `NEX_AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_SUPERVISED_PROCESS_POSTGRES_SMOKE=1`.
- Added regression coverage for skip/default behavior, profile guardrails,
  missing database URL, migration failure redaction, SQLite harness execution,
  failed-check reporting, cleanup verification, helper edges, and summary
  output.

## Smoke Flow

When enabled, the smoke:

- requires `NEX_AE_TEST_DATABASE_URL` and rejects non-test profiles/databases,
- runs AE migrations before API execution,
- records one `status_probe`/`MISSING` snapshot and one guarded
  `start_daemon`/`RUNNING` snapshot through AE APIs,
- reads the running snapshot through collection and detail APIs,
- verifies table, index, migration, row-count, pid, and JSONB observations with
  direct database queries,
- deletes the inserted snapshot/event rows and verifies cleanup.

## Guardrails

- The smoke records process evidence only; it does not invoke a daemon CLI or
  start/stop a subprocess.
- The default quality gate skips the write smoke until it is explicitly enabled.
- The smoke only accepts the test database profile and verifies that the
  database name ends in `_test`.
- Evidence redacts database passwords and rejects database URLs, local storage
  paths, provider secrets, service tokens, raw artifact payloads, raw execution
  payloads, and raw daemon runtime payloads.

## Evidence

```bash
./.venv/bin/python -m py_compile scripts/smoke/run_ae_artifact_retention_scheduler_daemon_supervised_process_postgres_smoke.py tests/test_ae_artifact_retention_scheduler_daemon_supervised_process_postgres_smoke.py
PYTHONPATH=services/_shared:services/nex-ae-api:scripts/db:scripts/smoke ./.venv/bin/pytest tests/test_ae_artifact_retention_scheduler_daemon_supervised_process_postgres_smoke.py -q --cov=run_ae_artifact_retention_scheduler_daemon_supervised_process_postgres_smoke --cov-branch --cov-report=term-missing
./scripts/quality/run_quality_gate.sh
```

## Next

- Slice 0576 should add AG's read-only supervised process projection foundation
  over the AE API evidence shape.
