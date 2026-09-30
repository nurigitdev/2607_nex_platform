# Slice 1148: MO provider readiness and resilience composition

## Goal

Compose active provider readiness, bounded retry policy, and process-local
execution telemetry into one privacy-safe operational projection.

## Result

- Readiness remains the authority for current route availability.
- A ready route with a last logical request failure is projected as degraded;
  unavailable and unknown readiness remain fail-closed.
- A successful request that required retries remains healthy while exposing
  retry pressure separately. Historical retries therefore do not create a
  permanent recovering state.
- The projection includes only public deployment identity, bounded retry
  policy, and aggregate counters. Endpoints, credentials, payloads, and raw
  exception details are excluded.
- The composition is process-local and adds no database table. Durable
  telemetry remains S116.

## Verification

```bash
./.venv/bin/pytest -q tests/test_mo_provider_resilience_composition.py
./.venv/bin/python \
  scripts/smoke/run_mo_provider_resilience_composition.py --summary
scripts/quality/run_slice_gate.sh --service nex-mo \
  --test tests/test_mo_provider_resilience_composition.py \
  --coverage-target services/nex-mo/nex_mo/provider_resilience.py \
  --smoke scripts/smoke/run_mo_provider_resilience_composition.py
```

## Quality Evidence

- Focused readiness, retry-telemetry, and composition regression: `38 passed`.
- Slice Gate: `514 passed`, `1` protected PostgreSQL smoke skip.
- Coverage: statement `99.71%`, branch `98.94%`; changed resilience scope
  reached statement `100.00%` and branch `100.00%`.
- Contract validation remained `119/177/145/7`.
- Composition smoke covered all three capabilities and separated one observed
  retry from current health (`6/6` checks).
