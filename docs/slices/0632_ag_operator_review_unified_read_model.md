# Slice 0632: AG Operator Review Unified Read-Model Projection

Slice 0632 adds the first S64 implementation layer: a read-only AG operator
review workbench projection over existing S63 note and export records.

## Scope

- Adds `nex_ag.operator_review_workbench`.
- Adds `GET /admin/v1/operator-review/workbench`.
- Groups `ag_op_notes` and `ag_ev_exports` records by target service, kind, and
  id.
- Returns safe note refs with hash/preview fields and safe evidence export refs
  with redacted manifest metadata.
- Adds no new database table.

## Decision

- The workbench read model is AG-owned and read-only.
- Note/export mutations remain in the existing S63 routes.
- Dashboard wiring, issue candidates, and PostgreSQL workbench smoke remain
  later S64 slices.

## Verification

```bash
PYTHONPATH=services/_shared:services/nex-ag ./.venv/bin/pytest tests/test_nex_ag_operator_review_workbench.py -q --cov=nex_ag.operator_review_workbench --cov-branch --cov-report=term-missing
./scripts/quality/run_quality_gate.sh
```
