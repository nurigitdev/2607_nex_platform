# Slice 1099: AE MVP Acceptance PostgreSQL/Live Smoke

## Goal

Produce fresh, protected acceptance evidence from the existing S109 end-to-end
path without duplicating its browser or generation orchestration.

## Implementation

- `run_ae_mvp_acceptance_postgres_live_smoke.py` opts in only through
  `NEX_AE_MVP_ACCEPTANCE_POSTGRES_LIVE_SMOKE=1`.
- It delegates the actual execution to the S109 protected smoke, which runs
  migrations and one authenticated Chromium request across actual
  `nex_ae_test`, `nex_cx_test`, and all three DGX providers.
- It validates the exact PostgreSQL identities, Qwen provider models, zero
  provider failures, durable terminal states, `VERIFIED_RESPONSE`, and the
  browser secret boundary.
- After S109 cleanup returns, it opens new database sessions and proves that
  the fixed smoke owner has zero rows in the AE chat/workspace and CX
  generation admission/execution/job tables.
- It emits only the three fresh S110 gate fragments owned by this smoke:
  `postgres_smoke`, `live_grounded_generation`, and `operations_handoff`.
  Regression and coverage evidence remain the responsibility of Slice 1101.

## Privacy

The evidence excludes document text, prompts, generated answers, credentials,
database URLs, provider endpoints, API keys, storage paths, and browser session
material. Failures expose bounded error classes or codes only.

## Verification

```bash
./.venv/bin/pytest -q tests/test_ae_mvp_acceptance_postgres_live_smoke.py \
  --cov=run_ae_mvp_acceptance_postgres_live_smoke \
  --cov-branch --cov-report=term-missing

./scripts/quality/run_slice_gate.sh --service nex-ae-api \
  --test tests/test_ae_mvp_acceptance_postgres_live_smoke.py \
  --coverage-target scripts/smoke/run_ae_mvp_acceptance_postgres_live_smoke.py \
  --smoke scripts/smoke/run_ae_mvp_acceptance_postgres_live_smoke.py
```

The protected execution additionally requires the two test database URLs,
the configured DGX provider settings, and an installed Chromium runtime.

## Protected Evidence

Executed on 2026-09-29 against the actual test infrastructure:

- PostgreSQL identities: `nex_ae_user@nex_ae_test` and
  `nex_cx_user@nex_cx_test`
- Live models: `Qwen3-Embedding-4B`, `Qwen3-Reranker-4B`, and `Qwen3.5-4B`
- Provider capabilities: `3/3` succeeded with zero failed calls
- Chromium display state: `VERIFIED_RESPONSE`
- Durable states: AE `COMPLETED`, retrieval `READY`, generation `COMPLETED`,
  and job `SUCCEEDED`
- Post-cleanup residue: zero rows across all five independently queried probe
  surfaces
- Acceptance result: `11/11` checks and all three emitted gates passed

The machine-readable evidence was written outside the repository and contains
no database URL, provider endpoint, API key, prompt, source text, or generated
answer.
