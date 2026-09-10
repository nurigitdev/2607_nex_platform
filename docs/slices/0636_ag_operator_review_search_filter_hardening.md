# Slice 0636: AG Operator Review Search Filter Hardening

Slice 0636 hardens the S64 operator review workbench search boundary.

## Scope

- Adds `note_status`, `export_status`, `updated_from`, and `updated_to` filters
  to `/admin/v1/operator-review/workbench` and
  `/admin/v1/operator-review/workbench/rollups`.
- Normalizes ISO-8601 timestamp filters to UTC `Z` strings so SQLite regression
  and PostgreSQL smoke paths compare the same contract shape.
- Extends AG note/export stores so status and updated-at range filters are
  applied before record limits.
- Adds regression coverage for in-memory stores, SQLite stores, workbench
  projections, route validation, and rollup reuse of the same filters.

## Boundary

- No new database table is added.
- No raw note text, raw evidence body, storage path, token, provider key, or
  idempotency key is exposed by the workbench projection.
- PostgreSQL workbench/dashboard smoke evidence remains protected and planned
  for the dedicated S64 PostgreSQL smoke slice.

## Verification

```bash
./.venv/bin/python -m py_compile services/nex-ag/nex_ag/operator_reviews.py services/nex-ag/nex_ag/operator_review_workbench.py tests/test_nex_ag_operator_reviews.py tests/test_nex_ag_operator_review_exports.py tests/test_nex_ag_operator_review_workbench.py
PYTHONPATH=services/_shared:services/nex-ag ./.venv/bin/pytest tests/test_nex_ag_operator_review_workbench.py -q --cov=nex_ag.operator_review_workbench --cov-branch --cov-report=term-missing
PYTHONPATH=services/_shared:services/nex-ag ./.venv/bin/pytest tests/test_nex_ag_operator_reviews.py tests/test_nex_ag_operator_review_exports.py -q --cov=nex_ag.operator_reviews --cov-branch --cov-report=term-missing
./scripts/quality/run_quality_gate.sh
```
