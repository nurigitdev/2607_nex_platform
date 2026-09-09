# Slice 0627: AG Redacted Evidence Export Service

Slice 0627 adds the service facade for AG-owned redacted evidence exports.

## Scope

- Adds `OperatorEvidenceExportService` on top of the export store foundation.
- Requires `Idempotency-Key` for export mutations.
- Treats repeated matching requests as `REPLAYED` and conflicting reuse as
  `409 ag.evidence_export_idempotency_conflict`.
- Ignores caller-supplied `export_id` during service mutations so export ids
  remain AG-derived.
- Adds list/get service methods with target, trace, status, and operator
  filters.

## Verification

```bash
./.venv/bin/python -m py_compile services/nex-ag/nex_ag/operator_reviews.py tests/test_nex_ag_operator_review_exports.py
PYTHONPATH=services/_shared:services/nex-ag ./.venv/bin/pytest tests/test_nex_ag_operator_review_exports.py tests/test_nex_ag_operator_reviews.py -q --cov=nex_ag.operator_reviews --cov-branch --cov-report=term-missing
```

## Evidence

```text
110 passed, 1 warning
services/nex-ag/nex_ag/operator_reviews.py statement_coverage=100% branch_coverage=100%
```

## Next

Slice 0628 should wire protected AG export routes over this service facade.
