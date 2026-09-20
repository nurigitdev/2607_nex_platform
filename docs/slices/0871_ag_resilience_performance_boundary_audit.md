# Slice 0871: AG resilience and performance boundary audit

## Goal

Start S88 by fixing the resilience and bounded-performance boundary for NeX-AG
administrative read and evidence operations before changing runtime behavior.

## Decision

- NeX-AG owns its request admission, read budgets, source isolation, and
  performance projection.
- Reuse the shared API/worker database pool split and PostgreSQL statement
  timeout. Do not introduce a second engine factory or connection manager.
- Reuse the existing operations query options and maximum 500-item bound.
- Preserve server-side selection for audit evidence; clients do not supply raw
  event or export records.
- Add no S88 table. A targeted index migration is allowed only when an actual
  query shape and PostgreSQL evidence justify it.
- Keep load evidence bounded and non-destructive. S88 is not a distributed
  stress-test project and does not attempt automatic pool sizing.
- Keep retention, archive, and physical purge in S89. Keep final NeX-AG MVP
  acceptance and the CX transition checkpoint in S90.

Current defaults remain the baseline, not universal capacity promises:

| Workload | Pool | Overflow | Pool timeout | Statement timeout |
| --- | ---: | ---: | ---: | ---: |
| API | 5 | 10 | 30 seconds | 30,000 ms |
| Worker | 3 | 3 | 30 seconds | 60,000 ms |

The default page size for S88 is 50 and the hard maximum is 500. Later Slices
may choose a lower endpoint-specific bound but must not exceed the common cap.

## Slice Plan

- Slice 0871: boundary audit and refactoring checkpoint.
- Slice 0872: explicit performance budget and policy contract.
- Slice 0873: stable bounded pagination and ordering hardening.
- Slice 0874: concurrency admission and load-shedding guard.
- Slice 0875: source timeout and failure isolation.
- Slice 0876: database pool and latency operations projection.
- Slice 0877: query index and API contract hardening.
- Slice 0878: actual `nex_ag_test` bounded-load PostgreSQL smoke.
- Slice 0879: privacy, failure-mode, and performance runbook evidence.
- Slice 0880: S88 closure checkpoint.

## Verification

```bash
./.venv/bin/python \
  scripts/smoke/run_ag_resilience_performance_boundary_audit.py --summary
```

Expected summary:

```text
ag_resilience_performance_boundary=pass page_max=500 pool=5+10 new_table=False
```

```bash
./.venv/bin/pytest -q \
  tests/test_ag_resilience_performance_boundary_audit.py \
  --cov=run_ag_resilience_performance_boundary_audit \
  --cov-branch --cov-report=term-missing
```

Observed verification:

```text
boundary tests: 6 passed, runner statement/branch coverage 100%
aggregate regression: 5915 passed, 1 known warning
statement=72881/73762=98.805618068924%
branch=17084/17734=96.334724258487%
```
