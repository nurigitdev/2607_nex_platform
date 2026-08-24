# Slice 0329: AG Generation Quality Issue Detail PostgreSQL Smoke Evidence

## Scope

Extend the protected AG generation quality PostgreSQL smoke so it proves the
Slice 0326-0328 issue detail/runbook surface against the real `nex_ag_test`
database path.

## Implemented

- Extended `run_ag_generation_quality_postgres_smoke.py` to build:
  - `ag_generation_quality_issue_detail_projection.v1`
- Added smoke checks for:
  - issue detail JSON Schema validation;
  - metadata-gap runbook routing;
  - generation audit detail debug path;
  - redaction safety across stored event, dashboard, issue candidate, audit
    projection, and issue detail projection.
- Kept the smoke protected by:
  - `NEX_AG_GENERATION_QUALITY_POSTGRES_SMOKE=1`
  - `NEX_AG_GENERATION_QUALITY_POSTGRES_SMOKE_PROFILE=test`
- Verified the smoke against the actual `nex_ag_test` database URL.

## Evidence

Targeted regression:

```text
./.venv/bin/pytest tests/test_smoke_helpers.py -q
199 passed, 1 warning
```

Actual PostgreSQL test DB smoke:

```text
NEX_AG_TEST_DATABASE_URL='postgresql+psycopg://nex_ag_user:***@127.0.0.1:5432/nex_ag_test' \
NEX_AG_GENERATION_QUALITY_POSTGRES_SMOKE=1 \
NEX_AG_GENERATION_QUALITY_POSTGRES_SMOKE_PROFILE=test \
./.venv/bin/python scripts/smoke/run_ag_generation_quality_postgres_smoke.py --summary

ag_generation_quality_postgres_smoke=pass service=nex-ag db_env=NEX_AG_TEST_DATABASE_URL quality=WARN attention=1 events=1
```

JSON evidence highlights:

```text
projection_versions.issue_detail=ag_generation_quality_issue_detail_projection.v1
quality_status.issue_detail_runbook_id=ag.generation_quality.metadata_gap_triage.v1
checks.issue_detail_contract_valid=true
checks.issue_detail_runbook_surfaces_metadata_gap=true
checks.raw_values_absent_from_ag_evidence=true
```

Full quality gate:

```text
./scripts/quality/run_quality_gate.sh
2217 passed, 1 warning
statement_coverage=98.55%
branch_coverage=95.48%
contract_validation=pass schemas=52 examples=84 negative_examples=61 openapi=7
```
