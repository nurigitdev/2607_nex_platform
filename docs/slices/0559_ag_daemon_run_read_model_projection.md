# Slice 0559: AG daemon run read-model projection

## Scope

Add an AG operations projection over the AE-owned scheduler daemon run
collection/detail read-model routes from Slice 0558.

## Implementation

- Extended `AeArtifactOperationsClient`, `InMemoryAeArtifactOperationsClient`,
  and `HttpAeArtifactOperationsClient` with daemon run collection/detail reads.
- Added AG routes:
  `/admin/v1/operations/artifact-retention/scheduler-daemon-runs` and
  `/admin/v1/operations/artifact-retention/scheduler-daemon-runs/{daemon_run_record_id}`.
- Added collection/detail projection builders and summaries that expose safe
  daemon run, lifecycle, source-status, and operator-guidance metadata.
- Added query guardrails for scheduler id, result status, and bounded limit.
- Added protected PostgreSQL smoke evidence that writes AE daemon run rows,
  reads them through AE API routes, projects them through AG, and cleans up the
  test DB rows.

## Guardrails

- AE remains the system of record for daemon run persistence.
- AG reads through AE APIs only; it does not write AE daemon run rows, enqueue
  AE retention jobs, or control daemon processes.
- Projections are metadata-only and exclude database URLs, storage paths,
  storage refs, raw execution payloads, artifact payloads, and rendered content.
- The new PostgreSQL smoke is opt-in only:
  `NEX_AE_AG_ARTIFACT_RETENTION_SCHEDULER_DAEMON_RUN_READ_MODEL_POSTGRES_SMOKE=1`.

## Evidence

```bash
./.venv/bin/python -m py_compile services/nex-ag/nex_ag/artifact_operations.py tests/test_nex_ag_artifact_operations.py scripts/smoke/run_ae_ag_artifact_retention_scheduler_daemon_run_read_model_postgres_smoke.py tests/test_ae_ag_artifact_retention_scheduler_daemon_run_read_model_postgres_smoke.py
PYTHONPATH=tests:services/_shared:services/nex-ae-api:services/nex-ag:scripts/db:scripts/smoke ./.venv/bin/pytest tests/test_ae_ag_artifact_retention_scheduler_daemon_run_read_model_postgres_smoke.py tests/test_nex_ag_artifact_operations.py -q
NEX_AE_AG_ARTIFACT_RETENTION_SCHEDULER_DAEMON_RUN_READ_MODEL_POSTGRES_SMOKE=1 NEX_AE_TEST_DATABASE_URL=<test-db-url> ./.venv/bin/python scripts/smoke/run_ae_ag_artifact_retention_scheduler_daemon_run_read_model_postgres_smoke.py --summary
./scripts/quality/run_quality_gate.sh
```

## Next

- Slice 0560 can close S56 by checking the executable runtime, persistence,
  read-model API, AG projection, and protected smoke evidence as one package.
