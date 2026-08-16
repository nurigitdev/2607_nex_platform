# Slice 0307: Retrieval Threshold Decision PostgreSQL Smoke

## Scope

Add protected PostgreSQL smoke evidence for the AG retrieval threshold decision
surface. The smoke proves that AG can read persisted CX retrieval package score
samples from the `nex-cx` test database and surface the resulting threshold
readiness through the threshold, dashboard, and issue-candidate APIs.

This slice does not call remote embedding, reranker, or generation providers.

## Implemented

- Added `scripts/smoke/run_ag_retrieval_threshold_decision_postgres_smoke.py`.
- The smoke is skipped by default and only runs when
  `NEX_AG_RETRIEVAL_THRESHOLD_DECISION_POSTGRES_SMOKE=1`.
- The smoke is restricted to the `test` profile and resolves
  `NEX_CX_TEST_DATABASE_URL`.
- Before execution it runs the current `nex-cx` migrations.
- During execution it seeds 21 real `cx_retrieval_packages` rows:
  20 `retrieval_quality_v1` samples and 1
  `weighted_rrf_vector_bm25_v1` sample.
- It verifies a direct DB select plus AG API reads for:
  `/admin/v1/operations/retrieval-threshold-decisions`,
  `/admin/v1/operations/dashboard`, and
  `/admin/v1/operations/issue-candidates`.
- It cleans up seeded source/content/chunk/retrieval rows after the smoke run.
- Added the smoke as `ag_retrieval_threshold_decision_postgres` in
  `scripts/smoke/run_postgres_test_smoke_suite.py`.
- Added regression coverage for skip/profile/failure/redaction/main paths and a
  SQLite execution fixture.

## Evidence

- Targeted regression:
  `./.venv/bin/pytest tests/test_smoke_helpers.py::test_ag_threshold_postgres_smoke_skips_by_default tests/test_smoke_helpers.py::test_ag_threshold_postgres_smoke_rejects_non_test_profile tests/test_smoke_helpers.py::test_ag_threshold_postgres_smoke_reports_pass_without_leaking_secret tests/test_smoke_helpers.py::test_ag_threshold_postgres_smoke_reports_failures tests/test_smoke_helpers.py::test_ag_threshold_postgres_smoke_execute_with_sqlite_fixture tests/test_smoke_helpers.py::test_ag_threshold_postgres_smoke_helpers_cover_edges tests/test_smoke_helpers.py::test_ag_threshold_postgres_smoke_main_prints_summary_and_full_evidence tests/test_smoke_helpers.py::test_postgres_test_smoke_suite_reports_pass_without_leaking_secret -q`
- Protected PostgreSQL smoke against `nex_cx_test`:
  `NEX_CX_TEST_DATABASE_URL='postgresql+psycopg://nex_cx_user:nuri1004@127.0.0.1:5432/nex_cx_test' NEX_AG_RETRIEVAL_THRESHOLD_DECISION_POSTGRES_SMOKE=1 NEX_AG_RETRIEVAL_THRESHOLD_DECISION_POSTGRES_SMOKE_PROFILE=test ./.venv/bin/python scripts/smoke/run_ag_retrieval_threshold_decision_postgres_smoke.py --summary`

Observed summary:

```text
ag_retrieval_threshold_decision_postgres_smoke=pass service=nex-cx db_env=NEX_CX_TEST_DATABASE_URL decisions=2 samples=21 ready=1 insufficient=1 issues=2
```

Observed full evidence included skipped-current migrations, 21 seeded package
rows, 2 policy ids, 2 threshold decisions, dashboard sample count 21, 2 issue
candidates, and all smoke checks passing.
