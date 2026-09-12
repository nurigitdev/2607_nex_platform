# Slice 0678: AG operator review case lifecycle contract/OpenAPI hardening

## Intent

Freeze the S68 lifecycle read-model contract surface before live PostgreSQL smoke
evidence.

## Scope

- Extend `operator_review_case_workbench.v1.schema.json` for:
  - `ag_operator_review_case_action_outcomes.v1`
  - `ag_operator_review_case_assignment_workload.v1`
  - `ag_operator_review_case_closure_packet.v1`
- Add positive contract examples for action outcomes, assignment workload, and
  closure packet payloads.
- Register the new examples in `contracts/examples/index.json`.
- Add the protected closure packet route to `contracts/openapi/nex-ag.openapi.yaml`.
- Extend the OpenAPI workbench surface marker fields for lifecycle payloads.

## Decision

The lifecycle contracts remain read-model-only and do not introduce a lifecycle
or closure packet persistence table. The closure packet contract explicitly
requires `resolution_preview` to be `null` and
`resolution_preview_included=false`, because closure evidence should not carry
operator-authored resolution text.

## Verification

```bash
./.venv/bin/python scripts/quality/validate_contracts.py
PYTHONPATH=services/_shared:services/nex-ag ./.venv/bin/pytest tests/test_nex_ag_operator_review_cases.py tests/test_nex_ag_operations.py -q
```

## Result

Contract validation covers the new lifecycle examples, the extended workbench
schema, and the OpenAPI closure packet route.
