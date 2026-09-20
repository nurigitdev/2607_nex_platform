# Slice 0879: AG resilience privacy and failure runbook

## Goal

Turn the S88 failure boundaries and live performance evidence into deterministic,
privacy-safe operator actions.

## Implementation

- Exercises admission exhaustion, source timeout, source exception, API and
  worker pool saturation, pool-metric failure, and invalid cursor handling.
- Requires normalized error codes, retry guidance, counters, and projection
  states while rejecting database URLs, credentials, SQL, raw exceptions, and
  source payloads from evidence.
- Defines actions for latency-budget breach, missing migration/indexes,
  PostgreSQL connectivity, unstable pagination, and smoke cleanup failure.
- Requires all Slice 0871-0878 documents, the quality-gate hook, and Slice 0878
  live evidence for 25 requests, concurrency four, p95 budget, three indexes,
  migration presence, and zero residue.
- Introduces no table or migration.

## Verification

```bash
./.venv/bin/pytest -q \
  tests/test_ag_resilience_performance_privacy_runbook_evidence.py \
  --cov=run_ag_resilience_performance_privacy_runbook_evidence \
  --cov-branch --cov-report=term-missing

./.venv/bin/python \
  scripts/smoke/run_ag_resilience_performance_privacy_runbook_evidence.py \
  --summary
```

Observed verification:

```text
focused runbook tests: 8 passed
runbook evidence statement/branch: 100%
ag_resilience_privacy_runbook=pass surfaces=9 privacy=True postgres=True runbook=True
aggregate regression: 6000 passed, 1 known warning
statement=73563/74444=98.816560098866%
branch=17230/17880=96.364653243848%
```
