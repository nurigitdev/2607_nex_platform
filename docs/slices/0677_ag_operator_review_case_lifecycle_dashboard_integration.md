# Slice 0677: AG operator review case lifecycle dashboard integration

## Intent

Fold S68 lifecycle state into the unified AG operations dashboard so operators
can see assignment workload and closure packet entry points from the existing
case dashboard section.

## Scope

- Add assignment workload summary/items to the `operator_review_cases` dashboard
  section.
- Add closure packet path templates to the dashboard section and attention-item
  links.
- Reuse `ag_operator_review_case_assignment_workload.v1` from Slice 0674.
- Keep dashboard payloads read-only and redaction-safe.
- Extend the operations projection schema with optional dashboard lifecycle
  properties.

## Decision

The dashboard remains a projection over existing AG-owned sources. It does not
read closure packets eagerly and does not require a closure packet table. The
dashboard exposes the path operators can follow when a case needs lifecycle
debugging or closure evidence review.

## Verification

```bash
./.venv/bin/python -m py_compile services/nex-ag/nex_ag/operations.py tests/test_nex_ag_operations.py
PYTHONPATH=services/_shared:services/nex-ag ./.venv/bin/pytest tests/test_nex_ag_operations.py -q --cov=nex_ag.operations --cov-branch --cov-report=term-missing
./.venv/bin/python scripts/quality/validate_contracts.py
```

## Result

The targeted operations tests cover dashboard workload summary, unassigned
workload items, closure packet path templates, attention-item closure links,
filtered empty projections, and degraded case-store handling.
