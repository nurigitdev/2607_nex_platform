# Slice 0640: S64 Operator Review Workbench Closure

Slice 0640 closes S64 by checking the AG-owned operator review workbench
capability track.

## Scope

- Verifies required S64 files, runtime modules, contracts, OpenAPI paths, smoke
  scripts, tests, and Slice 0631-0640 docs.
- Confirms workbench and rollup routes remain AG-owned read-model projections
  over `ag_op_notes` and `ag_ev_exports`.
- Confirms dashboard and issue-candidate wiring use safe workbench counts,
  status, target refs, and runbook/action metadata.
- Confirms the protected PostgreSQL workbench smoke evidence path exists for
  the real `nex_ag_test` database.
- Confirms the privacy regression pack checks workbench, rollup, dashboard, and
  issue-candidate surfaces for forbidden leak labels.
- Confirms the default quality gate includes boundary, PostgreSQL smoke,
  privacy regression, and closure checkpoints.

## Decision

- No new database table is added in S64.
- `nex-ag` owns the workbench projection boundary.
- Source service records remain read-only from AG's perspective.
- Raw operator notes, raw evidence bodies, raw prompts, raw source text,
  storage paths, raw database URLs, provider keys, service tokens, and raw
  idempotency keys remain outside closure evidence.

## Verification

```bash
./.venv/bin/python -m py_compile scripts/smoke/run_s64_operator_review_workbench_closure.py tests/test_s64_operator_review_workbench_closure.py
PYTHONPATH=scripts/smoke ./.venv/bin/pytest tests/test_s64_operator_review_workbench_closure.py -q --cov=run_s64_operator_review_workbench_closure --cov-branch --cov-report=term-missing
PYTHONPATH=scripts/smoke ./.venv/bin/python scripts/smoke/run_s64_operator_review_workbench_closure.py --summary
./scripts/quality/run_quality_gate.sh
```

## Expected Summary

```text
s64_operator_review_workbench_closure=pass slice_range=0631-0640 required_files=37 boundary=ag_owned_operator_review_workbench_projection source_tables=ag_op_notes,ag_ev_exports smoke=test_db_workbench privacy=route_surface_regression
```
