# Slice 0598: AG operator-control execution route wiring

## Scope

Wire Slice 0597 operator-control execution projections into protected AG
operations routes.

## Decision

- AG exposes read-only admin routes for AE operator-control execution
  collection/detail evidence.
- Route validation normalizes action/status filters and rejects invalid service
  filters, execution statuses, idempotency statuses, and limits before calling
  AE.
- Missing AE detail responses become AG problem+json 404 responses.

## Implementation

- Added AG routes:
  - `GET /admin/v1/operations/artifact-retention/scheduler-daemon-operator-control-executions`
  - `GET /admin/v1/operations/artifact-retention/scheduler-daemon-operator-control-executions/{operator_control_execution_state_id}`
- Added execution query validation for action, execution status, idempotency
  status, scheduler id, and limit.
- Added route regression coverage for successful collection/detail responses,
  unauthorized access, invalid filters, missing detail, and AE source failure.

## Guardrails

- Routes require AG authorization and preserve the `nex-ae-api` service filter
  boundary.
- AG routes remain read-only: no direct database write, job enqueue, supervisor
  dispatch, process control, or physical deletion is performed.
- Projections remain metadata-only and redaction-safe.

## Evidence

```bash
./.venv/bin/python -m py_compile services/nex-ag/nex_ag/artifact_operations.py tests/test_nex_ag_artifact_operations.py
./.venv/bin/pytest tests/test_nex_ag_artifact_operations.py -q
./scripts/quality/run_quality_gate.sh
```

Results:

- Targeted AG regression: `92 passed`.
- Full quality gate: `4122 passed`, statement coverage `98.58%`, branch
  coverage `95.71%`.

## Next

- Slice 0599 should prove the AG routes against an AE service app backed by the
  real AE test database.
