# Slice 1030: AE Runtime Policy PostgreSQL Smoke Evidence

## Goal

Prove the S103 prompt registry, protected policy API, chat policy orchestration,
operational events, restart reads, and cleanup against the actual
`nex_ae_test` PostgreSQL database.

## Implementation

- Added an explicit-opt-in runner restricted to `nex_ae_user` and
  `nex_ae_test`.
- Runs all AE migrations before the probe and verifies the live database/role
  identity plus all required prompt, chat, and event tables.
- Seeds all four canonical AE prompt bindings twice to prove idempotency.
- Resolves a document-summary policy through the protected API and executes a
  grounded chat through deterministic retrieval/generation clients.
- Reopens SQLAlchemy stores and reads back the exact policy snapshot,
  generation package, prompt render event, and policy-bearing operational
  events.
- Deletes only the synthetic chat, render event, and operational events and
  verifies zero remaining smoke rows. Canonical prompt seeds remain installed.
- Registered the complete S103 smoke chain through Slice 1030 in the Full Gate.

## Decisions

- Remote providers are intentionally not used. This Slice proves AE
  persistence and orchestration boundaries; model-provider behavior is outside
  the S103 PostgreSQL evidence scope.
- The smoke is skipped unless `NEX_AE_RUNTIME_POLICY_POSTGRES_SMOKE=1` and an
  allowed test database URL are supplied.

## Verification

```bash
NEX_AE_RUNTIME_POLICY_POSTGRES_SMOKE=1 \
NEX_AE_TEST_DATABASE_URL='<test-database-url>' \
./.venv/bin/python \
  scripts/smoke/run_ae_runtime_policy_postgres_smoke.py --summary

scripts/quality/run_slice_gate.sh --service nex-ae-api \
  --test tests/test_ae_runtime_policy_postgres_smoke.py \
  --coverage-target services/nex-ae-api/nex_ae_api/prompt_persistence.py \
  --coverage-target services/nex-ae-api/nex_ae_api/runtime_policy_api.py \
  --smoke scripts/smoke/run_ae_runtime_policy_postgres_smoke.py
```

## Observed Evidence

- Actual PostgreSQL smoke: PASS on `nex_ae_test` as `nex_ae_user`.
- Migrations: `23` planned/current.
- PostgreSQL checks: `17/17`.
- Row evidence: `4` canonical bindings, `1` render event, `1` chat record,
  and `2` operational events.
- Synthetic row cleanup: `0` remaining.
- Slice Gate: PASS (`2088 passed`; statement `97.87%`, branch `95.65%`).
- Target coverage: prompt persistence and runtime-policy API statement/branch
  `100.00%`/`100.00%`.
- Contract validation: PASS (`96` schemas, `150` examples, `113` negative
  examples, `7` OpenAPI documents).
