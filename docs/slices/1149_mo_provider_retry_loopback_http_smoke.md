# Slice 1149: MO provider retry loopback HTTP smoke

## Goal

Exercise bounded provider retries through the real HTTP transport without
depending on external DGX availability or exposing private runtime values.

## Result

- A temporary loopback HTTP server injects `503 -> 200` for embedding and
  generation, and `429 + Retry-After: 0 -> 200` for reranking.
- All three calls use the production `httpx` transport path rather than an
  injected requester.
- The smoke verifies canonical request keys, authorization-header presence,
  normalized results, exact attempt counts, and retry telemetry.
- Evidence contains only aggregate counts and booleans. The ephemeral port,
  endpoint, authorization value, and request content are excluded.
- No PostgreSQL or external provider is involved because this Slice validates
  the process-local HTTP retry boundary only.

## Verification

```bash
./.venv/bin/pytest -q tests/test_mo_provider_retry_loopback_http_smoke.py
./.venv/bin/python \
  scripts/smoke/run_mo_provider_retry_loopback_http_smoke.py --summary
scripts/quality/run_slice_gate.sh --service nex-mo \
  --test tests/test_mo_provider_retry_loopback_http_smoke.py \
  --coverage-target services/nex-mo/nex_mo/provider_retry_transport.py \
  --smoke scripts/smoke/run_mo_provider_retry_loopback_http_smoke.py
```

## Quality Evidence

- Focused real-loopback HTTP tests: `3 passed`.
- Slice Gate: `517 passed`, `1` protected PostgreSQL smoke skip.
- Coverage: statement `99.71%`, branch `98.94%`; retry-transport scope
  remained statement `100.00%` and branch `100.00%`.
- Contract validation remained `119/177/145/7`.
- Loopback smoke executed six real HTTP requests across three capabilities and
  passed all `6/6` transport, normalization, telemetry, and privacy checks.
