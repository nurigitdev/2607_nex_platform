# Slice 0981: S98 CX Worker Operations and Resilience Closure

## Goal

Close S98 only when the CX worker execution, resilience, protected operations,
and actual PostgreSQL evidence remain complete and machine-checkable.

## Closure

S98 closes as `READY_FOR_S99` with:

- strict metadata-only execution and state transitions;
- PostgreSQL atomic claims and renewable compare-and-swap leases;
- bounded batch execution and cooperative cancellation checkpoints;
- classified bounded retry, poison handling, and dead-letter projection;
- heartbeat-backed readiness and graceful shutdown;
- restart-safe lease plus heartbeat reconciliation;
- protected worker readiness, reconciliation, cancellation, and dead-letter
  APIs with metadata-only operational events; and
- actual `nex_cx_test` concurrent claim, lease CAS, recovery, event persistence,
  cancellation, dead-letter, and zero-residue cleanup evidence.

## Frozen Boundary

- `service_jobs` and `service_worker_heartbeats` remain canonical; S98 added no
  table or migration.
- Worker processes remain externally supervised and execute bounded batches.
- Recovery requires both an expired lease and an unavailable heartbeat.
- Retry is bounded backoff followed by dead-letter; cancellation is
  cooperative at safe checkpoints.
- Operational projections contain metadata only.
- DGX providers are outside S98 and were not required for its PostgreSQL smoke.
- S99 is `CX asynchronous grounded generation execution and recovery
  hardening`; streaming transport, multi-attempt citation repair, and
  production provider SLO baselines remain deferred.

## Verification

```bash
./.venv/bin/pytest -q \
  tests/test_s98_cx_worker_operations_resilience_closure.py \
  tests/test_cx_worker_operations_resilience_boundary_audit.py \
  --cov=run_s98_cx_worker_operations_resilience_closure \
  --cov=run_cx_worker_operations_resilience_boundary_audit \
  --cov-branch --cov-report=term-missing
./.venv/bin/python \
  scripts/smoke/run_s98_cx_worker_operations_resilience_closure.py \
  --summary
NEX_CX_TEST_DATABASE_URL='<local test DB URL>' \
NEX_CX_WORKER_OPERATIONS_POSTGRES_SMOKE=1 \
NEX_CX_WORKER_OPERATIONS_POSTGRES_SMOKE_PROFILE=test \
scripts/quality/run_quality_gate.sh
```

The Full Gate repeats the actual Slice 0980 PostgreSQL smoke when its protected
environment flag is enabled. Provider-live smoke remains outside this
requirement.

## Observed Evidence

- Focused closure: `11 passed`; both closure and boundary runners reached
  `100%` statement and branch coverage.
- Full regression: `7618 passed` in `693.71s`.
- Repository coverage: `98.91%` statement and `96.68%` branch.
- Contract validation: `90` schemas, `141` examples, `106` negative cases,
  and `7` OpenAPI documents passed.
- Actual `nex_cx_test` smoke: all `23` checks passed with `6/6` unique
  concurrent claims, `4` expired leases recovered, and `0` residual rows.
- Closure summary: `components=8/8`, `gaps=8/8`, `postgres_checks=23`,
  `next=S99`; Full Gate exited with status `0`.
