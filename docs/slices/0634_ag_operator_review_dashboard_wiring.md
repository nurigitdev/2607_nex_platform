# Slice 0634: AG Operator Review Dashboard Wiring

Slice 0634 surfaces the S64 operator review workbench rollup inside the AG
operations dashboard.

## Scope

- Adds `operator_review_workbench` to
  `ag_operations_dashboard_snapshot_projection.v1`.
- Reuses the Slice 0632-0633 read model and rollup builders instead of adding a
  new table or write path.
- Wires `nex-ag` main so operator review routes and the dashboard share the
  same note/export stores.
- Updates the mock-first operations dashboard smoke to exercise the new section.
- Updates the operations projection contract and dashboard example.

## Boundary

- AG remains the owner of operator-review dashboard projection.
- `service_id` on `/admin/v1/operations/dashboard` is interpreted as the
  operator-review target service filter for this section.
- Source health is reported under `nex-ag` because `ag_op_notes` and
  `ag_ev_exports` remain AG-owned.
- PostgreSQL workbench/dashboard smoke evidence remains protected and deferred to
  the dedicated S64 smoke slice.

## Verification

```bash
PYTHONPATH=services/_shared:services/nex-ag ./.venv/bin/pytest tests/test_nex_ag_operations.py -q --cov=nex_ag.operations --cov-branch --cov-report=term-missing
PYTHONPATH=scripts/smoke ./.venv/bin/pytest tests/test_smoke_helpers.py -q
./scripts/quality/run_quality_gate.sh
```
