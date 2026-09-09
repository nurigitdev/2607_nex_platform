# Slice 0628: AG Redacted Evidence Export Routes

Slice 0628 wires protected runtime routes for AG-owned redacted evidence
exports.

## Scope

- Adds protected `POST /admin/v1/operator-review/evidence-exports`.
- Adds protected collection and detail reads for evidence exports.
- Reuses the S63 operator-review authorization boundary: service-token calls
  or admin user-token calls only.
- Emits one redacted AG operational event only for `NEW` export mutations.
- Keeps replay responses side-effect free.

## Verification

```bash
./.venv/bin/python -m py_compile services/nex-ag/nex_ag/operator_reviews.py tests/test_nex_ag_operator_review_exports.py
PYTHONPATH=services/_shared:services/nex-ag ./.venv/bin/pytest tests/test_nex_ag_operator_review_exports.py tests/test_nex_ag_operator_reviews.py -q --cov=nex_ag.operator_reviews --cov-branch --cov-report=term-missing
```

## Evidence

```text
115 passed, 1 warning
services/nex-ag/nex_ag/operator_reviews.py statement_coverage=100% branch_coverage=100%
```

## Next

Slice 0629 should prove the route and persistence path against the real
`nex_ag_test` PostgreSQL database.
