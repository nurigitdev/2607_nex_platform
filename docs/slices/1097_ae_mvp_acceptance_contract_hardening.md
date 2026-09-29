# Slice 1097: AE MVP Acceptance Contract Hardening

## Goal

Freeze the protected AE MVP acceptance projection with strict JSON Schema,
positive and negative fixtures, and AE OpenAPI `1.7.0`.

## Contract

- `ae_mvp_acceptance_report.v1` requires exactly nine gate results and permits
  only normalized reason codes, summary counts, advisory deferrals, trace ID,
  source status, and server-selected metadata.
- The accepted example and actual evaluator projection both validate against
  the same canonical JSON Schema.
- Negative fixtures prove that `raw_evidence` and `database_url` are rejected
  as additional properties.
- OpenAPI declares only `GET /admin/v1/operations/mvp-acceptance`; no mutation
  operation exists. The projection and nested gate/blocker objects all reject
  additional properties.

## Verification

```bash
./.venv/bin/pytest -q tests/test_nex_ae_mvp_acceptance_contracts.py
./.venv/bin/python scripts/quality/validate_contracts.py
```

No table or migration is added.
