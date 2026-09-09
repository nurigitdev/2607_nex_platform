# Slice 0626: AG Redacted Evidence Export Persistence

Slice 0626 adds the AG-owned persistence and contract foundation for redacted
operator evidence exports.

## Scope

- Adds the short AG-owned `ag_ev_exports` table migration.
- Splits target refs and operator refs into indexable columns.
- Stores only a redacted manifest plus SHA-256 hashes; raw evidence payloads,
  raw prompts, raw source text, storage paths, and idempotency keys are not
  persisted.
- Adds the `ag_redacted_evidence_export.v1` JSON Schema and a worker-result
  example contract.
- Adds in-memory and SQLAlchemy store coverage, including SQLite persistence
  regression tests and unavailable-store errors.

## Verification

```bash
./.venv/bin/python -m py_compile services/nex-ag/nex_ag/operator_reviews.py tests/test_nex_ag_operator_review_exports.py
./.venv/bin/python -m json.tool contracts/schemas/generation/ag_redacted_evidence_export.v1.schema.json
./.venv/bin/python -m json.tool contracts/examples/generation/ag_redacted_evidence_export.worker_result.json
PYTHONPATH=services/_shared:services/nex-ag ./.venv/bin/pytest tests/test_nex_ag_operator_review_exports.py tests/test_nex_ag_operator_reviews.py -q --cov=nex_ag.operator_reviews --cov-branch --cov-report=term-missing
```

## Evidence

```text
103 passed, 1 warning
services/nex-ag/nex_ag/operator_reviews.py statement_coverage=100% branch_coverage=100%
```

## Next

Slice 0627 should add the export service facade and idempotency API before
route wiring and PostgreSQL smoke evidence.
