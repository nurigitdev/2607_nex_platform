# Slice 0615: AE worker result read-model API

## Scope

Expose persisted AE operator-control execution worker results through protected
read-only AE collection/detail APIs.

## Decision

- No new database table is added in this slice.
- The read model uses the existing short `ae_op_exec_worker_results` table.
- AE remains the only owner of worker-result persistence.
- AG may later consume these records through protected AE APIs, but it must not
  read or write the AE database table directly.
- The collection route supports safe indexed filters:
  `scheduler_id`, `action`, `worker_status`,
  `operator_control_execution_state_id`,
  `operator_control_execution_request_id`, and `limit`.
- The detail route returns the validated safe worker-result record plus summary
  metadata; it does not expose raw worker command, transition-plan, supervisor
  result, database URL, or storage path payloads.

## Implementation

- Added worker-result collection/detail schema versions and read-model builders
  in the AE scheduler daemon module.
- Added protected AE GET routes:
  - `/api/v1/artifact-retention/scheduler-daemon-operator-control-execution-worker-results`
  - `/api/v1/artifact-retention/scheduler-daemon-operator-control-execution-worker-results/{operator_control_execution_worker_result_id}`
- Added the new route URLs to the scheduler API route catalog.
- Added regression coverage for builder projection safety, invalid filters,
  authenticated list/detail reads, empty filters, 404 detail lookup, and store
  unavailable responses.

## Evidence

```bash
./.venv/bin/python -m py_compile services/nex-ae-api/nex_ae_api/artifacts.py services/nex-ae-api/nex_ae_api/artifact_retention_scheduler_daemon.py tests/test_nex_ae_artifact_retention_scheduler_daemon_operator_control_execution_worker_routes.py tests/test_nex_ae_artifact_retention_scheduler_daemon_operator_control_execution_worker_result_persistence.py
PYTHONPATH=services/_shared:services/nex-ae-api ./.venv/bin/pytest tests/test_nex_ae_artifact_retention_scheduler_daemon_operator_control_execution_worker_routes.py tests/test_nex_ae_artifact_retention_scheduler_daemon_operator_control_execution_worker_result_persistence.py -q
./scripts/quality/run_quality_gate.sh
```

Observed targeted regression:

```text
46 passed, 1 warning
```

Observed quality gate:

```text
4361 passed, 1 warning
statement_coverage=98.58% threshold=95.00%
branch_coverage=95.73% threshold=85.00%
```

## PostgreSQL Posture

This slice does not add a new PostgreSQL smoke runner because it adds no schema
or write path. Slice 0614 already proves the underlying store against the real
`nex_ae_test` database, including migration, JSONB, upsert/select, and cleanup
evidence. A follow-up AG projection or AE read-model smoke can exercise these
new GET routes against PostgreSQL directly.

## Next

- Slice 0616 can add an AG worker-result projection foundation over these
  protected AE read-model APIs.
