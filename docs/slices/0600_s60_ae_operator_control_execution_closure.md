# Slice 0600: S60 AE operator-control execution closure

## Scope

Close the S60 operator-control execution track with a quality-gate checkpoint
covering Slice 0591-0600.

## Implementation

- Added `scripts/smoke/run_s60_ae_operator_control_execution_closure.py`.
- The closure verifies the full Slice 0591-0600 document sequence.
- It checks the S60 boundary audit, AE execution request/result contracts,
  execution state and transition state machine, protected AE routes, AE
  PostgreSQL smoke, AE persistence/read-model API, AG read-only projections, AG
  route wiring, AG-to-AE PostgreSQL smoke, and this closure checkpoint.
- It verifies quality-gate hooks for the S60 boundary audit, AE execution
  protected smoke, AG-to-AE persisted read-model protected smoke, and closure
  script.
- It scans S60 docs and service README notes for database URLs, provider keys,
  shared passwords, service tokens, idempotency keys, local paths, and raw
  private payload markers.

## Guardrails

- AE remains the only supervisor execution and persistence owner.
- Execution state and transition writes remain explicit through
  `persist_execution_state=true` and `persist_transition=true`.
- AG remains a read-only projection and admin route surface over AE APIs.
- `fake_dry_run_supervisor_persistent_dispatch` is still the only persisted
  dispatch mode covered by S60 smoke evidence.
- S60 does not enable real supervisor adapter invocation, subprocess
  start/stop, worker execution, JobQueue enqueue, or physical deletion.
- Protected PostgreSQL smoke remains opt-in and requires the real test DB.

## Evidence

```bash
./.venv/bin/python -m py_compile scripts/smoke/run_s60_ae_operator_control_execution_closure.py tests/test_s60_ae_operator_control_execution_closure.py
PYTHONPATH=scripts/smoke ./.venv/bin/pytest tests/test_s60_ae_operator_control_execution_closure.py -q --cov=run_s60_ae_operator_control_execution_closure --cov-branch --cov-report=term-missing
NEX_AE_AG_ARTIFACT_RETENTION_SCHEDULER_DAEMON_OPERATOR_CONTROL_EXECUTION_READ_MODEL_POSTGRES_SMOKE=1 NEX_AE_TEST_DATABASE_URL=postgresql+psycopg://nex_ae_user:***@127.0.0.1:5432/nex_ae_test PYTHONPATH=scripts/smoke:services/_shared:services/nex-ae-api:services/nex-ag:scripts/db ./.venv/bin/python scripts/smoke/run_ae_ag_artifact_retention_scheduler_daemon_operator_control_execution_read_model_postgres_smoke.py --summary
./scripts/quality/run_quality_gate.sh
```

Observed PostgreSQL smoke summary:

```text
ae_ag_artifact_retention_scheduler_daemon_operator_control_execution_read_model_postgres_smoke=pass service=nex-ae-api ag_service=nex-ag db_env=NEX_AE_TEST_DATABASE_URL states=1 transitions=1 ag_collection=200 ag_detail=200 cleanup_states=1 cleanup_transitions=1 live_db=true
```

Observed closure summary:

```text
s60_ae_operator_control_execution_closure=pass slice_range=0591-0600 required_files=31 boundary=ae_owned ag_projection=read_only persistence=explicit smoke=test_db_persisted_read_model
```

Observed quality gate coverage:

```text
statement_coverage=98.56% threshold=95.00%
branch_coverage=95.65% threshold=85.00%
```

## Next

- Slice 0601 can decide whether to move from metadata-only fake dispatch toward
  a more complete AE execution worker, or pause the artifact-retention track and
  return to CX/AE user-facing workflow work.
