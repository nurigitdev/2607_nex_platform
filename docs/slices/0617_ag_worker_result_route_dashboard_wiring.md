# Slice 0617: AG worker result route/dashboard wiring

## Scope

Expose AE-persisted operator-control execution worker results through protected
AG admin routes and include them in the artifact-retention operations smoke.

## Decision

- No new database table is added in this slice.
- AG remains a read-only projection facade over AE-owned persistence.
- The AE-owned source table remains `ae_op_exec_worker_results`.
- AG validates service, action, worker status, state id, request id, and limit
  filters before delegating to AE.
- Dashboard smoke remains mock-first; the PostgreSQL cross-service route smoke
  is reserved for the next slice so it can connect to the real `nex_ae_test`
  database explicitly.

## Implementation

- Added protected AG collection/detail routes:
  - `/admin/v1/operations/artifact-retention/scheduler-daemon-operator-control-execution-worker-results`
  - `/admin/v1/operations/artifact-retention/scheduler-daemon-operator-control-execution-worker-results/{operator_control_execution_worker_result_id}`
- Added query validation for `action`, `worker_status`, identity filters, and
  collection limit.
- Wired the routes to the Slice 0616 AG projection builders.
- Extended `run_ag_artifact_retention_automation_operations_smoke.py` so the
  operations smoke checks worker-result collection/detail route visibility and
  redaction.
- Added regression coverage for route success, auth/service guardrails, invalid
  filters, missing detail, AE-source failures, HTTP parameter shape, and smoke
  summary output.

## Evidence

```bash
./.venv/bin/python -m py_compile services/nex-ag/nex_ag/artifact_operations.py scripts/smoke/run_ag_artifact_retention_automation_operations_smoke.py tests/test_nex_ag_artifact_operations.py tests/test_ag_artifact_retention_automation_operations_smoke.py
PYTHONPATH=services/_shared:services/nex-ag:scripts/smoke ./.venv/bin/pytest tests/test_nex_ag_artifact_operations.py tests/test_ag_artifact_retention_automation_operations_smoke.py -q
PYTHONPATH=services/_shared:services/nex-ag ./.venv/bin/python scripts/smoke/run_ag_artifact_retention_automation_operations_smoke.py --summary
PYTHONPATH=services/_shared:services/nex-ag:scripts/smoke ./.venv/bin/pytest tests/test_nex_ag_artifact_operations.py tests/test_ag_artifact_retention_automation_operations_smoke.py -q --cov=nex_ag.artifact_operations --cov=run_ag_artifact_retention_automation_operations_smoke --cov-branch --cov-report=term-missing
```

Observed targeted regression:

```text
106 passed, 1 warning
```

Observed smoke summary:

```text
ag_artifact_retention_automation_operations_smoke=pass ... worker_results=2 worker_result_detail=SUCCEEDED ...
```

Observed targeted coverage:

```text
combined targeted coverage=97%
```

Observed quality gate:

```text
4366 passed, 1 warning
statement_coverage=98.57% threshold=95.00%
branch_coverage=95.69% threshold=85.00%
contract_validation=pass schemas=70 examples=101 negative_examples=75 openapi=7
```

## PostgreSQL Posture

This slice adds protected AG route wiring only. It does not add a new DB table
or mutate AE persistence. Slice 0618 should provide the actual cross-service
PostgreSQL smoke evidence against `NEX_AE_TEST_DATABASE_URL`.

## Next

- Slice 0618 should run AG-to-AE worker-result read-model routes against the
  real AE test database with migration, write/read projection, and cleanup
  evidence.
