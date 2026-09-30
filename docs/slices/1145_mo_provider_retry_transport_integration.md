# Slice 1145: MO provider retry transport integration

## Goal

Integrate the bounded retry executor with remote JSON transport while
preserving the existing single-attempt compatibility path.

## Result

- A retry transport decorator accepts a retry policy, sleeper, jitter source,
  and retry observer while the base transport remains single-attempt.
- HTTP 429 and transient 5xx failures carry a parsed delta-seconds
  `Retry-After` hint into the internal executor.
- Invalid, negative, empty, and HTTP-date `Retry-After` values are ignored;
  executor caps valid hints at the configured safety limit.
- Non-retryable 4xx responses are never retried. Generation read timeout is
  treated as ambiguous and remains single-attempt.
- Deterministic fault injection proves `503 -> 200` recovery without external
  network access or real sleep.

## Verification

```bash
./.venv/bin/pytest -q tests/test_mo_provider_retry_transport.py
./.venv/bin/python scripts/smoke/run_mo_provider_retry_transport.py --summary
scripts/quality/run_slice_gate.sh --service nex-mo \
  --test tests/test_mo_provider_retry_transport.py \
  --coverage-target services/nex-mo/nex_mo/provider_retry_transport.py \
  --smoke scripts/smoke/run_mo_provider_retry_transport.py
```

## Quality Evidence

- Focused transport compatibility regression: `110 passed`; architecture and
  closure recheck after refactoring: `22 passed`.
- The first Slice Gate exposed the S112 transport module line budget. Retry
  composition was moved into a decorator module and the base transport returned
  to `217/220` lines before continuing.
- Final Slice Gate: `492 passed`, `1` protected PostgreSQL skip.
- Coverage: statement `99.70%`, branch `98.88%`; transport, retry decorator,
  and Retry-After parser each reached `100%` statement and branch coverage.
- Deterministic smoke: two requests, one retry, and `4/4` checks passed.
