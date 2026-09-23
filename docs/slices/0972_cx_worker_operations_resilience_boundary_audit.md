# Slice 0972: CX Worker Operations and Resilience Boundary Audit

## Goal

Freeze the S98 worker operations and resilience boundary before changing CX
worker execution, lease recovery, cancellation, or operational APIs.

## Findings

- The shared JobQueue already provides PostgreSQL `FOR UPDATE SKIP LOCKED`
  claim, bounded retry/backoff, dead-letter state, replay lineage, cancellation,
  and service-local control routes.
- The shared worker runner already provides bounded batches, heartbeat
  emission, service-log emission, and fail-fast behavior.
- S93 provides a concrete durable CX ingestion worker with workload leases,
  checkpoint restart, expired-lease recovery, and an internal recovery route.
- These foundations are not yet assembled into a canonical CX worker execution
  contract. Cancellation is not cooperatively checked during execution, worker
  lifecycle shutdown is not explicit, and stale worker/job reconciliation is
  ingestion-specific.
- CX has no consolidated worker readiness/operations projection and no actual
  PostgreSQL concurrency/recovery evidence spanning queue claims, heartbeats,
  retries, cancellation, and restart reconciliation.

## Decision

- Reuse `service_jobs` and `service_worker_heartbeats`; S98 does not introduce
  another queue or worker-state table.
- Keep worker processes externally supervised. JobQueue controls finite work,
  not daemon process lifecycle.
- Use database atomic claim plus a workload lease. A queue lock alone is not a
  renewable execution lease.
- Cancellation is cooperative: queued jobs can terminate immediately, while a
  running handler observes a cancellation token at safe checkpoints.
- Retry remains bounded exponential backoff followed by dead-letter. Raw
  payloads and provider details stay outside operational projections.
- PostgreSQL is required for Slice 0980. DGX providers are not required in S98.
- The new tiered cadence is requirement-relative: Slice Gate on 0972-0981,
  Checkpoint Gate on 0976, and Full Gate on 0981.

## Slice Plan

1. Slice 0972: boundary audit and refactoring checkpoint.
2. Slice 0973: worker execution and state contract.
3. Slice 0974: durable claim/lease and concurrency controls.
4. Slice 0975: bounded runner and cooperative cancellation.
5. Slice 0976: retry/backoff/poison operations and Checkpoint Gate.
6. Slice 0977: heartbeat, readiness, and graceful shutdown.
7. Slice 0978: restart recovery and reconciliation.
8. Slice 0979: protected operations API and metadata-only observability.
9. Slice 0980: actual PostgreSQL concurrency/recovery smoke evidence.
10. Slice 0981: S98 closure and Full Gate.

## Verification

```bash
./.venv/bin/pytest -q \
  tests/test_cx_worker_operations_resilience_boundary_audit.py \
  --cov=run_cx_worker_operations_resilience_boundary_audit \
  --cov-branch --cov-report=term-missing
./.venv/bin/python \
  scripts/smoke/run_cx_worker_operations_resilience_boundary_audit.py \
  --summary
scripts/quality/run_slice_gate.sh --service nex-cx \
  --test tests/test_cx_worker_operations_resilience_boundary_audit.py \
  --coverage-target \
    scripts/smoke/run_cx_worker_operations_resilience_boundary_audit.py \
  --smoke \
    scripts/smoke/run_cx_worker_operations_resilience_boundary_audit.py
```

PostgreSQL and DGX are intentionally not invoked in this audit Slice.

Observed result:

- focused boundary audit: `5 passed`, statement `100%`, branch `100%`
- Slice Gate CX regression: `1,943 passed`
- Slice Gate statement coverage: `98.86%`
- Slice Gate branch coverage: `97.80%`
- contract validation: `89` schemas, `140` examples, `105` negative examples,
  and `7` OpenAPI documents
- boundary summary: `PASS`, foundations `6`, gaps `8`, open `8`, issues `0`
- Slice Gate elapsed time: `62.684s`
