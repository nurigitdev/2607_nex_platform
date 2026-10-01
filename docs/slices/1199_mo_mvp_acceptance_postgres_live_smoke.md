# Slice 1199: MO MVP PostgreSQL and DGX acceptance smoke

## Goal

Produce fresh S120 acceptance evidence from the actual `nex_mo_test` database,
all three DGX providers, and protected SSH runtime observation.

## Implementation

- The runner requires `NEX_MO_MVP_ACCEPTANCE_POSTGRES_LIVE_SMOKE=1` and delegates
  the real execution to the established S119 integrated acceptance path.
- The delegated path applies test-profile migrations, verifies the exact
  `nex_mo_user@nex_mo_test` identity, sends one real embedding, reranking, and
  generation request, and persists then removes unique telemetry rows.
- Live readiness and SSH runtime observation prove all three model identities,
  BF16 precision, GPU evidence, four ready sources, and three ready capabilities.
- The runner emits only normalized `postgres_smoke`,
  `live_provider_acceptance`, and `oa_transition_handoff` gate fragments.
- Provider payloads, endpoints, API keys, database URLs/passwords, SSH targets,
  process commands, and local absolute paths are excluded.

## Verification

```bash
./.venv/bin/pytest -q tests/test_mo_mvp_acceptance_postgres_live_smoke.py
NEX_MO_MVP_ACCEPTANCE_POSTGRES_LIVE_SMOKE=1 \
NEX_MO_OPERATIONS_LIVE_ACCEPTANCE_PROFILE=test \
NEX_MO_PROVIDER_MODE=live \
NEX_MO_TEST_DATABASE_URL='<protected nex_mo_test URL>' \
./.venv/bin/python \
  scripts/smoke/run_mo_mvp_acceptance_postgres_live_smoke.py --summary
```

## Executed Evidence

Executed on 2026-10-01 against the actual test infrastructure:

- PostgreSQL identity and migration state: `nex_mo_user@nex_mo_test`, current.
- Live providers and expected models: embedding, reranking, generation `3/3`.
- SSH runtime/BF16 healthy capabilities: `3/3`.
- Protected acceptance checks: `8/8`; targeted PostgreSQL residue: `0`.
- The protected pytest path executed without skip: `1 passed`.
- Slice Gate: `1042 passed, 6 skipped`; statement coverage `99.87%`, branch
  coverage `99.56%`; runner scope `100%/100%`.

The ordinary Slice Gate leaves protected infrastructure tests disabled; the
actual runner and protected pytest results above are the non-skipped evidence.
Next Slice: `1200`.
