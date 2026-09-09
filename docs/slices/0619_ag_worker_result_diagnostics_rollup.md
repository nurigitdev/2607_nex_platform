# Slice 0619: AG worker result diagnostics rollup

## Scope

Add a protected AG diagnostics rollup over AE-persisted operator-control
execution worker results.

## Decision

- No new database table is added in this slice.
- AG continues to consume AE-owned worker-result data only through AE APIs.
- The AE-owned source table remains `ae_op_exec_worker_results`.
- Diagnostics are read-only and metadata-only: they expose counts, status
  posture, hash-presence checks, safe-projection checks, status-path checks, and
  recommended operator actions without copying raw worker commands, transition
  plans, supervisor payloads, database URLs, or storage paths.
- PostgreSQL smoke is not required for this slice because Slice 0618 already
  proved the real AE test DB write/read/AG projection path.

## Implementation

- Added
  `ag_artifact_operation_retention_daemon_operator_control_execution_worker_result_diagnostics_projection.v1`.
- Added
  `diagnose_artifact_retention_daemon_operator_control_execution_worker_results`.
- Added protected AG route:
  `/admin/v1/operations/artifact-retention/scheduler-daemon-operator-control-execution-worker-result-diagnostics`.
- The route validates the same service/action/worker-status/identity/limit
  filters as the worker-result collection route, then delegates to the AE
  worker-result collection read-model API through the configured AG source
  client.
- Diagnostics classify the rollup as `NO_RESULTS`, `READY`, or `ATTENTION`.
  Attention covers failed/blocked worker results, failed supervisor results,
  incomplete hash bundles, unsafe metadata flags, raw payload markers, and
  status-path mismatches.

## Evidence

```bash
./.venv/bin/python -m py_compile services/nex-ag/nex_ag/artifact_operations.py
PYTHONPATH=services/_shared:services/nex-ag ./.venv/bin/pytest tests/test_nex_ag_artifact_operations.py -q
PYTHONPATH=services/_shared:services/nex-ag ./.venv/bin/pytest tests/test_nex_ag_artifact_operations.py -q --cov=nex_ag.artifact_operations --cov-branch --cov-report=term-missing
./scripts/quality/run_quality_gate.sh
```

Observed targeted regression:

```text
105 passed, 1 warning
```

Observed targeted coverage:

```text
nex_ag.artifact_operations: 97%
```

Observed quality gate:

```text
4380 passed, 1 warning
statement_coverage=98.57% threshold=95.00%
branch_coverage=95.69% threshold=85.00%
contract_validation=pass schemas=70 examples=101 negative_examples=75 openapi=7
```

## Next

- Slice 0620 should close S62 with a worker-result persistence/read-model
  checkpoint covering Slice 0611-0619.
