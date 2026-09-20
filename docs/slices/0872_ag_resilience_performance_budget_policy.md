# Slice 0872: AG resilience and performance budget policy

## Goal

Define one validated NeX-AG performance policy before pagination, admission,
timeout, and bounded-load behavior are wired into runtime paths.

## Implementation

- Added `nex_ag.resilience_performance` as the canonical S88 policy builder.
- Reused shared `DatabasePoolSettings` for API and worker pool projections.
- Added environment overrides under `NEX_AG_PERF_*` without storing secrets or
  database URLs in the policy projection.
- Validated page-size ordering, the 500-item hard cap, admission capacity versus
  configured API pool capacity, smoke concurrency, request count, slow-operation
  threshold, and source timeout versus PostgreSQL statement timeout.
- Kept statement timeout `0` as the existing explicit disable behavior while
  preserving bounded admission and page limits.

## Defaults

| Budget | Default |
| --- | ---: |
| Default page size | 50 |
| Maximum page size | 500 |
| Maximum in-flight AG operations | 8, capped by configured API pool capacity |
| Admission wait | 100 ms |
| Source timeout | 2,000 ms |
| Slow operation threshold | 1,000 ms |
| Bounded smoke requests | 25 |
| Bounded smoke concurrency | 4 |
| Bounded smoke p95 target | 1,500 ms |

These values are operational starting points, not production capacity claims.
Slice 0878 will record actual `nex_ag_test` bounded-load evidence.

## Verification

```bash
./.venv/bin/pytest -q tests/test_nex_ag_resilience_performance.py \
  --cov=nex_ag.resilience_performance --cov-branch --cov-report=term-missing
```

Observed verification:

```text
policy tests: 15 passed, module statement/branch coverage 100%
aggregate regression: 5930 passed, 1 known warning
statement=72940/73821=98.806572655477%
branch=17102/17752=96.338440739072%
```
