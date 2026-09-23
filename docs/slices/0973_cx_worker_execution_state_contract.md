# Slice 0973: CX Worker Execution and State Contract

## Goal

Define a strict metadata-only worker execution contract before adding lease,
cancellation, retry, or reconciliation behavior.

## Implementation

- Added `cx_worker_execution.v1` with separate queue and worker-execution state.
- Registered the current ingestion, processing, and remediation workloads.
- Added strict state transitions for claim, run, cancellation request, success,
  retry scheduling, dead-letter, and cancellation.
- Added monotonic state versions and timestamps, attempt metadata, worker
  identity, lease expiry, and safe error codes.
- Added a whitelist projection that excludes payloads, links, idempotency keys,
  prompts, source text, and provider details.
- Added positive and negative JSON contract fixtures. The negative fixture
  proves that raw payload fields are rejected.
- No database table or migration was added.

## Verification

```bash
./.venv/bin/pytest -q tests/test_nex_cx_worker_contracts.py \
  --cov=nex_cx.worker_contracts --cov-branch --cov-report=term-missing
./.venv/bin/python scripts/quality/validate_contracts.py
scripts/quality/run_slice_gate.sh --service nex-cx \
  --test tests/test_nex_cx_worker_contracts.py \
  --coverage-target services/nex-cx/nex_cx/worker_contracts.py \
  --smoke scripts/smoke/run_cx_worker_operations_resilience_boundary_audit.py
```

PostgreSQL and DGX are not required for this deterministic contract Slice.

Observed result:

- focused regression: `32 passed`
- Slice Gate: `1963 passed`
- statement coverage: `98.88%`
- branch coverage: `97.84%`
- `nex_cx.worker_contracts`: `100%` statement and branch coverage
- contract validation: `90` schemas, `141` positive examples, `106`
  negative examples, and `7` OpenAPI documents
