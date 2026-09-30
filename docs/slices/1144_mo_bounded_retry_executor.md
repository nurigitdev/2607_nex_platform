# Slice 1144: MO bounded retry executor

## Goal

Execute retry policy with deterministic, bounded, and observable behavior
without coupling tests to wall-clock sleep.

## Result

- Added a generic retry executor that returns the result plus exact attempt and
  retry counts.
- Added bounded exponential full-jitter delay calculation and capped
  `Retry-After` support.
- Sleeper, jitter source, and retry observer are injectable. Unit and smoke
  evidence therefore perform no real wait or network call.
- Non-retryable failures, exhausted budgets, and ambiguous generation failures
  immediately re-raise the original safe `ProviderRouteError`.
- Retry events contain only capability, attempt, delay, failure kind, and
  decision reason; provider-private values are absent.

## Verification

```bash
./.venv/bin/pytest -q tests/test_mo_provider_retry_executor.py
./.venv/bin/python scripts/smoke/run_mo_provider_retry_executor.py --summary
scripts/quality/run_slice_gate.sh --service nex-mo \
  --test tests/test_mo_provider_retry_executor.py \
  --coverage-target services/nex-mo/nex_mo/provider_retry.py \
  --smoke scripts/smoke/run_mo_provider_retry_executor.py
```

## Quality Evidence

- Focused retry regression: `25 passed`.
- Slice Gate: `480 passed`, `1` protected PostgreSQL skip.
- Coverage: statement `99.70%`, branch `98.85%`; retry executor scope reached
  `100%` statement and branch coverage.
- Deterministic smoke: three attempts, two retries, and `5/5` checks passed.
