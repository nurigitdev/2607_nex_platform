# Slice 0637: AG Operator Review OpenAPI Schema Examples

Slice 0637 freezes the public contract for the S64 operator review workbench
and rollup routes.

## Scope

- Adds `operator_review_workbench.v1.schema.json` and
  `operator_review_workbench_rollup.v1.schema.json`.
- Adds positive contract fixtures for workbench and rollup responses.
- Adds negative fixtures for raw operator note leakage and invalid attention
  statuses.
- Adds OpenAPI paths for `/admin/v1/operator-review/workbench` and
  `/admin/v1/operator-review/workbench/rollups`.
- Adds contract regression assertions so schema/index/OpenAPI wiring cannot be
  accidentally dropped.

## Boundary

- No runtime storage behavior changes.
- No new database table is added.
- PostgreSQL workbench smoke evidence remains the dedicated Slice 0638 task.

## Verification

```bash
PYTHONPATH=scripts/quality ./.venv/bin/pytest tests/test_contract_validation.py -q --cov=validate_contracts --cov-branch --cov-report=term-missing
./.venv/bin/python scripts/quality/validate_contracts.py
./scripts/quality/run_quality_gate.sh
```
