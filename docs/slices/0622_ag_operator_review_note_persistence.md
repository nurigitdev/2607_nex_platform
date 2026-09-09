# Slice 0622: AG Operator Review Note Persistence

Slice 0622 adds the AG-owned persistence foundation for operator review notes.

## Scope

- Adds the short `ag_op_notes` table.
- Splits target refs, operator refs, trace id, and status into indexable
  columns.
- Stores free-form operator note text as SHA-256 hash plus bounded preview.
- Keeps raw note body and raw idempotency keys outside the persisted contract.
- Adds in-memory and SQLAlchemy store coverage for SQLite regression.

## Evidence

The later S63 targeted regression covers the persistence foundation:

```bash
PYTHONPATH=services/_shared:services/nex-ag ./.venv/bin/pytest tests/test_nex_ag_operator_reviews.py -q --cov=nex_ag.operator_reviews --cov-branch --cov-report=term-missing
```
