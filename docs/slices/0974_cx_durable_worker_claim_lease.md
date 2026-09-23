# Slice 0974: CX Durable Worker Claim and Lease

## Goal

Turn the existing atomic `service_jobs` claim into an explicit renewable CX
worker lease without adding another queue or worker-state table.

## Implementation

- Reused PostgreSQL `FOR UPDATE SKIP LOCKED` queue claim as the exclusive
  admission point.
- Reused `service_jobs.locked_by` and `locked_at` as the durable lease owner and
  renewal timestamp.
- Added owner-checked lease inspection and expiry calculation with a bounded
  TTL policy.
- Added compare-and-swap renewal on the expected `locked_at` value so stale or
  competing workers cannot extend another execution.
- Added canonical claim-to-`cx_worker_execution.v1` composition for ingestion,
  processing, and remediation workloads.
- Kept projections metadata-only; queue payloads are never returned.
- Added no table or migration. Actual PostgreSQL concurrent claim behavior is
  reserved for Slice 0980.

## Verification

```bash
./.venv/bin/pytest -q tests/test_nex_cx_worker_leases.py \
  --cov=nex_cx.worker_leases --cov-branch --cov-report=term-missing
scripts/quality/run_slice_gate.sh --service nex-cx \
  --test tests/test_nex_cx_worker_leases.py \
  --test tests/test_cx_worker_operations_resilience_boundary_audit.py \
  --coverage-target services/nex-cx/nex_cx/worker_leases.py \
  --smoke scripts/smoke/run_cx_worker_operations_resilience_boundary_audit.py
```

Observed result:

- focused regression: `14 passed`
- Slice Gate: `1972 passed`
- statement coverage: `98.89%`
- branch coverage: `97.87%`
- `nex_cx.worker_leases`: `100%` statement and branch coverage
- contract validation: `90` schemas, `141` positive examples, `106`
  negative examples, and `7` OpenAPI documents

PostgreSQL and DGX are not required for this Slice.
