# Slice 0979: CX Worker Operations API and Observability

## Goal

Expose protected, metadata-only CX worker operations without weakening the
durable lease, cancellation, dead-letter, or restart-reconciliation rules.

## Implementation

- Added service-token-protected worker readiness, reconciliation plan/apply,
  cooperative cancellation, and dead-letter projection routes under
  `/internal/v1/workers`.
- Kept readiness and dead-letter inspection available in memory mode while
  failing reconciliation closed unless PostgreSQL lease persistence exists.
- Wired the production CX runtime to the worker database session factory and
  the specialized durable-ingestion recovery handler.
- Added cancellation and reconciliation event taxonomy entries with only job,
  state, and aggregate count metadata.
- Documented all five internal routes in the CX OpenAPI contract.
- Added no table or migration.

## Verification

```bash
./.venv/bin/pytest -q tests/test_nex_cx_worker_operations.py \
  tests/test_nex_runtime_operational_events.py \
  tests/test_cx_contract_api_drift_audit.py \
  --cov=nex_cx.worker_operations --cov-branch \
  --cov-report=term-missing
scripts/quality/run_slice_gate.sh --service nex-cx \
  --test tests/test_nex_cx_worker_operations.py \
  --test tests/test_cx_worker_operations_resilience_boundary_audit.py \
  --coverage-target services/nex-cx/nex_cx/worker_operations.py \
  --smoke scripts/smoke/run_cx_worker_operations_resilience_boundary_audit.py
```

Observed result:

- Slice Gate: `2024 passed`
- statement coverage: `98.94%`
- branch coverage: `97.95%`
- `nex_cx.worker_operations`: `100%` statement and branch coverage
- contract validation: `90` schemas, `141` positive examples, `106`
  negative examples, and `7` OpenAPI documents

PostgreSQL concurrency and restart-recovery evidence remains reserved for
Slice 0980.
