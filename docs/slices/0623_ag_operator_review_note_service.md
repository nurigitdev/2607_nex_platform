# Slice 0623: AG Operator Review Note Service

Slice 0623 adds the service facade for AG-owned operator review notes.

## Scope

- Adds `OperatorReviewNoteService`.
- Requires `Idempotency-Key` for note mutations.
- Treats repeated matching requests as `REPLAYED` and conflicting key reuse as
  `409 ag.operator_review_note_idempotency_conflict`.
- Ignores caller-supplied note ids during service mutations so AG remains the
  note id authority.
- Adds list/get service methods with target, trace, status, and operator
  filters.

## Evidence

The S63 service regression is covered by:

```bash
PYTHONPATH=services/_shared:services/nex-ag ./.venv/bin/pytest tests/test_nex_ag_operator_reviews.py -q --cov=nex_ag.operator_reviews --cov-branch --cov-report=term-missing
```
