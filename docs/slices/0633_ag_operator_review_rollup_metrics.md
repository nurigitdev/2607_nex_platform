# Slice 0633: AG Operator Review Rollup Metrics

Slice 0633 adds safe rollup metrics over the Slice 0632 operator review
workbench read model.

## Scope

- Adds `ag_operator_review_workbench_rollup.v1`.
- Adds `GET /admin/v1/operator-review/workbench/rollups`.
- Counts targets, notes, exports, open notes, resolved notes, high-urgency
  active notes, failed exports, ready exports, and evidence items.
- Derives target-level attention states from safe status/severity counts only.
- Adds no new database table.

## Decision

- Rollups are derived from the read model, not persisted.
- `FAILED` evidence exports produce `BLOCKED` attention.
- active `HIGH` or `URGENT` notes produce `ATTENTION`.
- active lower-severity notes produce `OPEN`.
- Dashboard wiring remains deferred to Slice 0634.

## Verification

```bash
PYTHONPATH=services/_shared:services/nex-ag ./.venv/bin/pytest tests/test_nex_ag_operator_review_workbench.py -q --cov=nex_ag.operator_review_workbench --cov-branch --cov-report=term-missing
./scripts/quality/run_quality_gate.sh
```
