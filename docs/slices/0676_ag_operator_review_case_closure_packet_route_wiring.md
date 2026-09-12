# Slice 0676: AG operator review case closure packet route wiring

## Intent

Expose the S68 closure packet foundation through a protected AG service route.

## Scope

- Add `GET /admin/v1/operator-review/cases/{case_id}/closure-packet`.
- Reuse the existing AG operator review authorization guard.
- Reuse the service-level closure packet wrapper from Slice 0675.
- Allow bounded `evidence_limit` and `timeline_limit` query parameters.
- Keep the packet read-model-only and non-persistent.

## Decision

The closure packet route is a protected diagnostic/operator route over existing
AG-owned sources. It does not mutate lifecycle state and does not introduce a
closure packet table. Missing cases use the existing operator review case
problem response path.

## Verification

```bash
./.venv/bin/python -m py_compile services/nex-ag/nex_ag/operator_review_cases.py tests/test_nex_ag_operator_review_cases.py
PYTHONPATH=services/_shared:services/nex-ag ./.venv/bin/pytest tests/test_nex_ag_operator_review_cases.py -q --cov=nex_ag.operator_review_cases --cov-branch --cov-report=term-missing
```

## Result

The targeted route tests cover authorized closure packet reads, missing cases,
unauthorized access, bounded evidence/timeline windows, emitted event evidence,
and raw payload redaction.
