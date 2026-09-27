# Slice 1010: AE PostgreSQL and browser current-state re-audit

## Goal

Apply the current AE migration chain to the actual `nex_ae_test` database and
prove catalog state, a representative domain upsert/select/rollback, privacy
posture, and deterministic Chromium readiness.

## Decision

- The smoke is protected and only accepts `nex_ae_user@nex_ae_test`.
- All 22 migrations must be applied or already recorded exactly.
- Expected long source identifiers are compared using PostgreSQL's 63-byte
  normalization, while the actual catalog must remain within the limit.
- The domain probe uses synthetic generation-feedback metadata, performs insert,
  conflict upsert, select, rollback, and post-rollback absence verification.
- The browser probe launches actual Chromium through Playwright readiness.
- Evidence is metadata-only and follows the accompanying privacy runbook.

## Verification

```bash
NEX_AE_CURRENT_STATE_POSTGRES_REAUDIT=1 \
NEX_AE_TEST_DATABASE_URL='<test-database-url>' \
./.venv/bin/python \
  scripts/smoke/run_ae_current_state_postgres_reaudit.py --summary

./.venv/bin/pytest -q tests/test_ae_current_state_postgres_reaudit.py \
  --cov=nex_ae_api.postgres_reaudit \
  --cov=run_ae_current_state_postgres_reaudit \
  --cov-branch --cov-report=term-missing
```

Observed verification:

- Protected smoke activation: enabled; actual target `nex_ae_test` with role
  `nex_ae_user`.
- Migration evidence: `22/22`; core tables `15`; missing migrations/tables,
  forbidden private columns, and failed checks all `0`.
- Domain probe: insert, conflict upsert, select, transaction rollback, and
  post-rollback absence all observed against `ae_generation_feedback`.
- Browser evidence: actual Playwright Chromium readiness `PASS`.
- Focused tests: `21 passed`; the evaluator and runner both reached `100%`
  statement and branch coverage.
- Protected Slice Gate: `1,916 passed`; statement coverage `97.80%`; branch
  coverage `95.48%`.
- Contract validation: `92` schemas, `145` examples, `109` negative examples,
  and `7` OpenAPI documents passed.
