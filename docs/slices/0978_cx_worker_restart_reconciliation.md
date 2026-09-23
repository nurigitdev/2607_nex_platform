# Slice 0978: CX Worker Restart Reconciliation

## Goal

Recover abandoned RUNNING jobs after process restart without allowing a stale
or merely slow worker to create duplicate execution.

## Implementation

- Added a read-only reconciliation plan over durable RUNNING jobs, leases, and
  worker heartbeats.
- Recovery requires both an expired lease and an unavailable heartbeat.
- A stale heartbeat with an active lease waits for lease expiry; an expired
  lease with a fresh heartbeat waits for heartbeat loss.
- Missing durable lease ownership is routed to manual review rather than
  guessed.
- Generic jobs use the bounded retry/dead-letter settlement policy.
- Durable ingestion jobs require their workload-specific checkpoint recovery
  handler; absent handlers fail closed without changing queue state.
- Applying the same plan again is idempotent and reports `ALREADY_SETTLED`.
- No new table or migration was added.

## Verification

```bash
./.venv/bin/pytest -q tests/test_nex_cx_worker_reconciliation.py \
  --cov=nex_cx.worker_reconciliation --cov-branch \
  --cov-report=term-missing
scripts/quality/run_slice_gate.sh --service nex-cx \
  --test tests/test_nex_cx_worker_reconciliation.py \
  --test tests/test_cx_worker_operations_resilience_boundary_audit.py \
  --coverage-target services/nex-cx/nex_cx/worker_reconciliation.py \
  --smoke scripts/smoke/run_cx_worker_operations_resilience_boundary_audit.py
```

Observed result:

- focused regression: `19 passed`
- Slice Gate: `2013 passed`
- statement coverage: `98.93%`
- branch coverage: `97.94%`
- `nex_cx.worker_reconciliation`: `100%` statement and branch coverage
- contract validation: `90` schemas, `141` positive examples, `106`
  negative examples, and `7` OpenAPI documents

PostgreSQL and DGX are not required here; actual PostgreSQL recovery evidence
is reserved for Slice 0980.
