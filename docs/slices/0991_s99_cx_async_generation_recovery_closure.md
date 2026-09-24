# Slice 0991: S99 CX Async Generation and Recovery Closure

## Goal

Close S99 only when asynchronous grounded-generation admission, execution,
recovery, owner operations, contracts, and actual PostgreSQL evidence remain
complete and machine-checkable.

## Closure

S99 closes as `READY_FOR_S100` with:

- deterministic metadata-only jobs in the existing `service_jobs` queue;
- immutable owner-private request envelopes outside queue and database rows;
- idempotent enqueue, in-progress join, and terminal replay behavior;
- S98 bounded worker execution with deterministic mock-provider coverage;
- retry, cancellation, attempt exhaustion, and expired-lease recovery;
- owner-scoped admission, polling, cancellation, and cross-owner hiding;
- JSON Schema, OpenAPI, negative privacy fixtures, and metadata-only events;
- actual `nex_cx_test` execution, retry, recovery, cancellation, restart read,
  replay, isolation, event persistence, and zero-residue cleanup evidence.

## Frozen Boundary

- The synchronous generation API remains compatible.
- S99 adds no database table or migration.
- Complete request and output text remain owner-private filesystem payloads;
  PostgreSQL and queue rows retain metadata and integrity references only.
- Remote embedding, reranker, and generation providers are not required for
  S99 closure because the current environment cannot reach them.
- Live remote async smoke, streaming transport, multi-attempt citation repair,
  and production provider SLO baselines remain deferred.
- The canonical title and detailed scope of S100 must be reviewed before S100
  implementation begins; this closure hands off only the requirement number.

## Verification

```bash
./.venv/bin/pytest -q \
  tests/test_s99_cx_async_generation_recovery_closure.py \
  tests/test_cx_async_generation_recovery_boundary_audit.py \
  --cov=run_s99_cx_async_generation_recovery_closure \
  --cov=run_cx_async_generation_recovery_boundary_audit \
  --cov-branch --cov-report=term-missing
./.venv/bin/python \
  scripts/smoke/run_s99_cx_async_generation_recovery_closure.py --summary
NEX_CX_TEST_DATABASE_URL='<local test DB URL>' \
NEX_CX_ASYNC_GENERATION_POSTGRES_SMOKE=1 \
NEX_CX_ASYNC_GENERATION_POSTGRES_SMOKE_PROFILE=test \
scripts/quality/run_quality_gate.sh
```

The Full Gate repeats the actual Slice 0990 PostgreSQL smoke when its protected
environment flag is enabled. Remote-provider smoke remains skipped until
connectivity is restored.

## Observed Evidence

- Focused closure verification: `11 passed`; both closure and boundary audit
  runners reached `100%` statement and branch coverage.
- Full Gate: `7,700 passed` in `715.63s`; repository coverage remained above
  the previous full baseline at `98.92%` statement and `96.70%` branch.
- Contract validation: `91` schemas, `142` positive examples, `107` negative
  examples, and `7` OpenAPI documents passed.
- Protected PostgreSQL smoke connected to `nex_cx_test` and passed all `21`
  checks: three jobs reached `SUCCEEDED`, one reached `CANCELLED`, retry and
  expired-lease recovery converged, owner isolation held, and cleanup left
  zero rows.
- S99 closure reported `components=8/8`, `gaps=8/8`, and `next=S100`.
- Remote-provider smoke was intentionally skipped because the current
  environment cannot reach the providers; deterministic mock coverage passed.
- Full Gate exited with status `0`.
