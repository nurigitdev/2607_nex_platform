# Slice 0589: AG-to-AE operator-control PostgreSQL smoke evidence

## Scope

Prove the AG operator-control policy and preview routes against an AE
test-database-backed service app.

## Implementation

- Added
  `scripts/smoke/run_ae_ag_artifact_retention_scheduler_daemon_operator_control_postgres_smoke.py`.
- Added a protected smoke bridge that lets AG call AE's
  `scheduler-daemon-operator-control-policy` and
  `scheduler-daemon-operator-control-preview` routes through an AE TestClient
  wired to the real AE test database.
- The smoke checks AG policy, status-probe preview, and restart preview routes,
  including header idempotency precedence, safe operator subject projection,
  preview-only guardrails, restart stop-then-start command preview, and AE
  bridge route statuses.
- The smoke verifies database health, migration/table/index readiness, and that
  preview calls leave AE supervised-process row counts unchanged.
- Registered the protected smoke runner in the default quality gate; it skips
  unless explicitly enabled.

## Guardrails

- The smoke only runs when
  `NEX_AE_AG_ARTIFACT_RETENTION_SCHEDULER_DAEMON_OPERATOR_CONTROL_POSTGRES_SMOKE=1`.
- The runner requires `NEX_AE_TEST_DATABASE_URL` and rejects non-test profiles.
- AG still does not dispatch supervisor commands, write AE persistence, enqueue
  AE jobs, or signal AE subprocesses directly.
- Evidence redacts database passwords, provider keys, idempotency keys, local
  paths, and unsafe request fields.

## Evidence

```bash
./.venv/bin/python -m py_compile scripts/smoke/run_ae_ag_artifact_retention_scheduler_daemon_operator_control_postgres_smoke.py tests/test_ae_ag_artifact_retention_scheduler_daemon_operator_control_postgres_smoke.py
./.venv/bin/pytest tests/test_ae_ag_artifact_retention_scheduler_daemon_operator_control_postgres_smoke.py -q
./scripts/quality/run_quality_gate.sh
NEX_AE_AG_ARTIFACT_RETENTION_SCHEDULER_DAEMON_OPERATOR_CONTROL_POSTGRES_SMOKE=1 NEX_AE_TEST_DATABASE_URL='postgresql+psycopg://nex_ae_user:***@127.0.0.1:5432/nex_ae_test' ./.venv/bin/python scripts/smoke/run_ae_ag_artifact_retention_scheduler_daemon_operator_control_postgres_smoke.py --summary
```

Results:

- Targeted regression: `11 passed`.
- Full quality gate: `3986 passed`, statement coverage `98.59%`, branch
  coverage `95.81%`.
- Protected PostgreSQL smoke:
  `ae_ag_artifact_retention_scheduler_daemon_operator_control_postgres_smoke=pass ... restart=READY ... unchanged=true live_db=true`.

## Next

- Slice 0590 should close S59 with a quality-gate, smoke-evidence, redaction,
  and docs checkpoint for the AE-owned, AG-dispatched operator-control surface.
