# Slice 0595: AE operator-control execution PostgreSQL smoke evidence

## Scope

Add protected PostgreSQL smoke evidence for the Slice 0594 AE operator-control
execution routes.

## Decision

- The smoke is opt-in and requires
  `NEX_AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_OPERATOR_CONTROL_EXECUTION_POSTGRES_SMOKE=1`.
- The only allowed profile is `test`, so the smoke must resolve
  `NEX_AE_TEST_DATABASE_URL` and reject dev/prod URLs.
- The smoke runs AE migrations, performs a real `SELECT 1` health probe, checks
  existing daemon process/supervisor tables and indexes, then calls the
  execution and transition routes through the protected AE API surface.
- The route remains metadata-only in this slice. The smoke verifies before/after
  row counts are unchanged for supervised-process and supervisor persistence.

## Implementation

- Added
  `scripts/smoke/run_ae_artifact_retention_scheduler_daemon_operator_control_execution_postgres_smoke.py`.
- Registered the smoke runner in the default quality gate, where it skips until
  explicitly enabled.
- Added regression coverage for skip, profile guard, missing test DB URL,
  redaction, SQLite-backed route harness, failed-check detection, helper edges,
  and CLI output.

## Guardrails

- Slice 0595 does not add execution persistence tables.
- Slice 0595 does not invoke the supervisor adapter.
- Slice 0595 does not persist supervisor results/events, enqueue jobs, run
  workers, start subprocesses, stop subprocesses, or enable physical deletion.
- Database URLs, passwords, provider API keys, local storage paths, raw artifact
  payloads, raw execution payloads, and raw supervised process snapshots remain
  excluded from evidence.

## Evidence

```bash
./.venv/bin/python -m py_compile scripts/smoke/run_ae_artifact_retention_scheduler_daemon_operator_control_execution_postgres_smoke.py tests/test_ae_artifact_retention_scheduler_daemon_operator_control_execution_postgres_smoke.py
PYTHONPATH=scripts/smoke:services/_shared:services/nex-ae-api ./.venv/bin/pytest tests/test_ae_artifact_retention_scheduler_daemon_operator_control_execution_postgres_smoke.py -q --cov=run_ae_artifact_retention_scheduler_daemon_operator_control_execution_postgres_smoke --cov-branch --cov-report=term-missing
NEX_AE_ARTIFACT_RETENTION_SCHEDULER_DAEMON_OPERATOR_CONTROL_EXECUTION_POSTGRES_SMOKE=1 NEX_AE_TEST_DATABASE_URL=postgresql+psycopg://nex_ae_user:***@127.0.0.1:5432/nex_ae_test PYTHONPATH=scripts/smoke:services/_shared:services/nex-ae-api ./.venv/bin/python scripts/smoke/run_ae_artifact_retention_scheduler_daemon_operator_control_execution_postgres_smoke.py --summary
./scripts/quality/run_quality_gate.sh
```

## Next

- Slice 0596 should add the AE-owned execution persistence/read-model API so
  admitted/replayed/transitioned execution evidence can be stored and queried.
