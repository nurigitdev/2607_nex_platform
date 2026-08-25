# Slice 0344: AG Remediation Task API/Repository Foundation

## Scope

Expose a protected AG task surface for generation remediation actions and add a
repository boundary that can run in memory for regression tests or through
SQLAlchemy once the PostgreSQL table is introduced.

This slice intentionally stops before adding the production PostgreSQL
migration. Slice 0345 owns the concrete `ag_generation_remediation_tasks`
table, PostgreSQL smoke evidence, and migration-gate wiring.

## Implemented

- Added `GenerationRemediationTaskStore` for deterministic in-memory task
  persistence.
- Added `SqlAlchemyGenerationRemediationTaskStore` for the upcoming
  `ag_generation_remediation_tasks` table.
- Added protected AG routes:
  - `POST /admin/v1/generation-audit/generations/{cx_generation_id}/remediation-tasks`
  - `GET /admin/v1/generation-audit/generations/{cx_generation_id}/remediation-tasks`
  - `GET /admin/v1/generation-audit/generations/{cx_generation_id}/remediation-tasks/{remediation_action_id}`
  - `PATCH /admin/v1/generation-audit/generations/{cx_generation_id}/remediation-tasks/{remediation_action_id}`
- Added status transition validation for remediation task updates.
- Emitted safe operational events for task creation and status updates.
- Registered the new remediation routes in `nex-ag`.
- Extended the AG OpenAPI contract with remediation task request, list, and
  status update schemas.

## Evidence

Targeted regression:

```text
./.venv/bin/pytest tests/test_nex_ag_generation_remediation.py -q
46 passed
```

Contract validation:

```text
./.venv/bin/python scripts/quality/validate_contracts.py
contract_validation=pass schemas=56 examples=88 negative_examples=65 openapi=7
```

Full quality gate:

```text
./scripts/quality/run_quality_gate.sh
2379 passed, 1 warning
statement_coverage=98.55% threshold=95.00%
branch_coverage=95.66% threshold=85.00%
contract_validation=pass schemas=56 examples=88 negative_examples=65 openapi=7
```

Next slice:

```text
Slice 0345: remediation PostgreSQL smoke evidence
```
