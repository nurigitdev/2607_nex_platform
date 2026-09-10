# Slice 0642: AG Operator Review Case Persistence Foundation

Slice 0642 adds the AG-owned persistence foundation for operator review cases.

## Scope

- Adds the `ag_op_cases` PostgreSQL migration.
- Adds an in-memory and SQLAlchemy-backed case store.
- Adds safe case record builders, list/mutation response builders, source refs,
  assignment refs, idempotency signatures, and metadata redaction flags.
- Keeps route wiring, action command handling, dashboard correlation, contracts,
  and protected PostgreSQL smoke evidence deferred to later S65 slices.

## Decision

- `ag_op_cases` is the S65 case table name and stays under the table-name length
  guard from Slice 0641.
- Case records split target references into indexed columns:
  `target_service`, `target_kind`, `target_id`, `trace_id`, and `request_id`.
- Case assignment uses indexable `assignee_id` plus a safe `assignment_ref`
  object.
- Free-text resolutions are stored as `resolution_hash` plus
  `resolution_preview`; raw comments are not stored.
- Action history remains operational-event-first in this slice.

## Verification

```bash
./.venv/bin/python -m py_compile services/nex-ag/nex_ag/operator_review_cases.py tests/test_nex_ag_operator_review_cases.py
PYTHONPATH=services/_shared:services/nex-ag ./.venv/bin/pytest tests/test_nex_ag_operator_review_cases.py -q --cov=nex_ag.operator_review_cases --cov-branch --cov-report=term-missing
./scripts/quality/run_quality_gate.sh
```
