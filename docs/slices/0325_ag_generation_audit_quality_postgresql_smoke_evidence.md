# Slice 0325: AG Generation Audit Quality PostgreSQL Smoke Evidence

## Scope

Add protected PostgreSQL smoke evidence for the AG generation audit quality
surface introduced in Slice 0324.

The smoke intentionally uses the existing AG `service_operational_events`
foundation instead of creating a new generation-audit persistence table. The
generation audit projection itself is still produced from deterministic
CX/AE-shaped payloads, while the smoke proves that AG can apply migrations,
write/read `nex_ag_test`, surface quality attention in the operations dashboard,
and produce an issue candidate without leaking raw prompt/provider material.

## Implemented

- Added `scripts/smoke/run_ag_generation_quality_postgres_smoke.py`.
- Added protected env guard:
  - `NEX_AG_GENERATION_QUALITY_POSTGRES_SMOKE=1`
  - `NEX_AG_GENERATION_QUALITY_POSTGRES_SMOKE_PROFILE=test`
  - `NEX_AG_TEST_DATABASE_URL=...`
- Added migration + SQLAlchemy operational event write/read evidence against
  the AG test database.
- Added dashboard and issue-candidate checks for:
  - `ag_generation_quality_dashboard_section.v1`;
  - `generation_quality_attention_required.v1`;
  - `MISSING_CX_GROUNDED_RESPONSE_QUALITY_FIELDS`.
- Added redaction checks for raw prompt, provider URL, and API key shaped
  inputs.
- Added the runner to the full quality gate smoke sweep and the optional
  PostgreSQL test smoke suite.

## Runtime Behavior

By default, the smoke runner is skipped and returns protected evidence. When
enabled with the test profile, it runs AG migrations, writes one smoke
operational event, reads it back, builds the generation quality dashboard
surface, verifies the issue candidate, and deletes the smoke row.

## Evidence

Targeted regression:

```text
./.venv/bin/pytest tests/test_smoke_helpers.py -q
199 passed, 1 warning
```

Protected default smoke:

```text
./.venv/bin/python scripts/smoke/run_ag_generation_quality_postgres_smoke.py --summary
ag_generation_quality_postgres_smoke=skipped reason=NEX_AG_GENERATION_QUALITY_POSTGRES_SMOKE
```

Actual PostgreSQL test DB smoke:

```text
NEX_AG_TEST_DATABASE_URL='postgresql+psycopg://nex_ag_user:***@127.0.0.1:5432/nex_ag_test' \
NEX_AG_GENERATION_QUALITY_POSTGRES_SMOKE=1 \
NEX_AG_GENERATION_QUALITY_POSTGRES_SMOKE_PROFILE=test \
./.venv/bin/python scripts/smoke/run_ag_generation_quality_postgres_smoke.py --summary

ag_generation_quality_postgres_smoke=pass service=nex-ag db_env=NEX_AG_TEST_DATABASE_URL quality=WARN attention=1 events=1
```

Full quality gate:

```text
./scripts/quality/run_quality_gate.sh
2207 passed, 1 warning
statement_coverage=98.54%
branch_coverage=95.47%
contract_validation=pass schemas=51 examples=83 negative_examples=60 openapi=7
```
