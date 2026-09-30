# Slice 1143: MO provider retry policy and failure taxonomy

## Goal

Define capability-specific retry budgets and distinguish timeout phases before
adding retry execution.

## Result

- Added immutable, environment-backed retry policies with a hard maximum of
  five attempts and defaults of `3/3/2` for embedding/reranking/generation.
- Added bounded base delay, maximum delay, and `Retry-After` cap settings.
- Refined timeout failures into connect, read, write, pool, and legacy generic
  timeout categories while retaining the existing safe external error codes.
- Generation retries remain blocked for ambiguous read/write/pool/generic
  timeout and malformed-response outcomes. Connection failures remain eligible.
- Policy projections contain no provider URL, credential, payload, or exception
  detail. This Slice performs no sleep and no remote call.

## Verification

```bash
./.venv/bin/pytest -q tests/test_mo_provider_retry_policy.py
./.venv/bin/python scripts/smoke/run_mo_provider_retry_policy.py --summary
scripts/quality/run_slice_gate.sh --service nex-mo \
  --test tests/test_mo_provider_retry_policy.py \
  --coverage-target services/nex-mo/nex_mo/provider_retry.py \
  --coverage-target services/nex-mo/nex_mo/provider_transport.py \
  --smoke scripts/smoke/run_mo_provider_retry_policy.py
```

## Quality Evidence

- Focused policy and compatibility regression: `105 passed`; focused policy
  regression after branch completion: `16 passed`.
- Slice Gate: `471 passed`, `1` protected PostgreSQL skip.
- Coverage: statement `99.69%`, branch `98.83%`; both changed modules reached
  `100%` statement and branch coverage.
- Contract validation remained `119/177/145/7` with zero schema drift.
