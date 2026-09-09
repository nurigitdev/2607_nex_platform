# Slice 0616: AG worker result projection foundation

## Scope

Add an AG read-only projection foundation for AE-persisted operator-control
execution worker results.

## Decision

- No new database table is added in this slice.
- AG consumes worker-result evidence through protected AE read-model APIs only.
- The AE-owned short table remains `ae_op_exec_worker_results`.
- AG does not write AE persistence, enqueue AE jobs, dispatch supervisor
  adapters, or control AE daemon processes.
- The projection accepts both the existing nested worker execution response and
  the persisted worker-result record shape introduced by Slice 0615.
- The projection carries safe status, transition path, supervisor-result counts,
  and hashes while excluding raw worker command, transition-plan, supervisor
  result, database URL, storage path, and secret payload data.

## Implementation

- Extended the AG AE-source client protocol with worker-result collection/detail
  read-model methods.
- Added in-memory and HTTP client implementations for:
  - `/api/v1/artifact-retention/scheduler-daemon-operator-control-execution-worker-results`
  - `/api/v1/artifact-retention/scheduler-daemon-operator-control-execution-worker-results/{operator_control_execution_worker_result_id}`
- Added AG collection/detail projection builders with source-status and
  operator-guidance metadata.
- Added worker-result operations summary support for succeeded, failed, blocked,
  supervisor-result, failed-supervisor, and latest-observed rollups.
- Hardened the shared worker-result projection helper so persisted top-level
  status/hash fields are supported without exposing raw execution payloads.

## Evidence

```bash
./.venv/bin/python -m py_compile services/nex-ag/nex_ag/artifact_operations.py tests/test_nex_ag_artifact_operations.py
PYTHONPATH=services/_shared:services/nex-ag ./.venv/bin/pytest tests/test_nex_ag_artifact_operations.py -q
PYTHONPATH=services/_shared:services/nex-ag ./.venv/bin/pytest tests/test_nex_ag_artifact_operations.py -q --cov=nex_ag.artifact_operations --cov-branch --cov-report=term-missing
./scripts/quality/run_quality_gate.sh
```

Observed targeted regression:

```text
100 passed, 1 warning
```

Observed targeted AG module coverage:

```text
services/nex-ag/nex_ag/artifact_operations.py coverage=97%
```

Observed quality gate:

```text
4364 passed, 1 warning
statement_coverage=98.58% threshold=95.00%
branch_coverage=95.70% threshold=85.00%
contract_validation=pass schemas=70 examples=101 negative_examples=75 openapi=7
```

## PostgreSQL Posture

This slice does not add a new PostgreSQL smoke runner because it introduces AG
projection/client foundation only. It creates no table and no DB mutation path.
The next route/smoke slices can exercise the projection against the real
`nex_ae_test` database through AE's protected read-model API.

## Next

- Slice 0617 can expose these projections through protected AG admin routes and
  dashboard wiring.
