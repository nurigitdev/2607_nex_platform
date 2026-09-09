# Slice 0624: AG Operator Review Note Routes

Slice 0624 wires protected runtime routes for AG-owned operator review notes.

## Scope

- Adds protected `POST /admin/v1/operator-review/notes`.
- Adds protected collection and detail reads for operator notes.
- Allows service-token callers and admin user-token callers only.
- Emits one redacted AG operational event only for `NEW` note mutations.
- Keeps replay responses side-effect free.

## Evidence

The route-level regression is covered by:

```bash
PYTHONPATH=services/_shared:services/nex-ag ./.venv/bin/pytest tests/test_nex_ag_operator_reviews.py -q --cov=nex_ag.operator_reviews --cov-branch --cov-report=term-missing
```
