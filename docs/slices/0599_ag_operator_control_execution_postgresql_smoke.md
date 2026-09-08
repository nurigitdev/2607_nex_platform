# Slice 0599: AG operator-control execution PostgreSQL smoke evidence

## Scope

Prove the Slice 0598 AG operator-control execution routes against AE
operator-control execution read models backed by the real AE test database.

## Decision

- The smoke is opt-in and requires
  `NEX_AE_AG_ARTIFACT_RETENTION_SCHEDULER_DAEMON_OPERATOR_CONTROL_EXECUTION_READ_MODEL_POSTGRES_SMOKE=1`.
- The only allowed profile is `test`, so the smoke must resolve
  `NEX_AE_TEST_DATABASE_URL` and reject non-test profiles.
- The smoke writes one persisted AE execution state and one transition using
  explicit `persist_execution_state=true` and `persist_transition=true`, reads
  them through the AG collection/detail routes, then deletes the targeted rows.
- The smoke checks scoped row counts, not global table totals, so it remains
  stable even when the shared test database already contains unrelated rows.

## Implementation

- Added
  `scripts/smoke/run_ae_ag_artifact_retention_scheduler_daemon_operator_control_execution_read_model_postgres_smoke.py`.
- Registered the protected smoke runner in the default quality gate, where it
  skips until explicitly enabled.
- Added regression coverage for skip, profile guard, missing DB URL, redaction,
  SQLite-backed persisted route harness, failed-check detection, cleanup
  verification failure, bridge error handling, helper edges, and CLI output.
- Backfilled Slice 0597/0598 documentation index entries so S60 evidence is
  contiguous.

## Guardrails

- The persisted state uses `fake_dry_run_supervisor_persistent_dispatch`; the
  smoke does not invoke a real supervisor adapter or start/stop subprocesses.
- AG reads through AE APIs only and still does not write AE persistence, enqueue
  jobs, or perform process control.
- Evidence redacts database passwords, provider keys, idempotency keys, local
  paths, raw artifact payloads, raw execution requests, and nested transition
  state payloads.

## Evidence

```bash
./.venv/bin/python -m py_compile scripts/smoke/run_ae_ag_artifact_retention_scheduler_daemon_operator_control_execution_read_model_postgres_smoke.py tests/test_ae_ag_artifact_retention_scheduler_daemon_operator_control_execution_read_model_postgres_smoke.py
PYTHONPATH=scripts/smoke:services/_shared:services/nex-ae-api:services/nex-ag:scripts/db ./.venv/bin/pytest tests/test_ae_ag_artifact_retention_scheduler_daemon_operator_control_execution_read_model_postgres_smoke.py -q --cov=run_ae_ag_artifact_retention_scheduler_daemon_operator_control_execution_read_model_postgres_smoke --cov-branch --cov-report=term-missing
NEX_AE_AG_ARTIFACT_RETENTION_SCHEDULER_DAEMON_OPERATOR_CONTROL_EXECUTION_READ_MODEL_POSTGRES_SMOKE=1 NEX_AE_TEST_DATABASE_URL=postgresql+psycopg://nex_ae_user:***@127.0.0.1:5432/nex_ae_test PYTHONPATH=scripts/smoke:services/_shared:services/nex-ae-api:services/nex-ag:scripts/db ./.venv/bin/python scripts/smoke/run_ae_ag_artifact_retention_scheduler_daemon_operator_control_execution_read_model_postgres_smoke.py --summary
./scripts/quality/run_quality_gate.sh
```

## Next

- Slice 0600 should close S60 with route, persistence, PostgreSQL smoke,
  redaction, and quality-gate evidence.
