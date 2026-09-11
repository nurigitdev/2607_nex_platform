# Slice 0667: AG operator review case evidence/admission contract hardening

## Intent

Freeze the S67 evidence-link and action-admission API payload shapes at the
contract layer before PostgreSQL smoke evidence.

## Scope

- Extend `operator_review_case_workbench.v1.schema.json` with:
  - `ag_operator_review_case_evidence_links.v1`
  - `ag_operator_review_case_action_admission.v1`
  - the Slice 0666 workbench-detail `evidence_links` and `action_admission`
    summary blocks.
- Add positive contract examples for evidence links and action admission.
- Update the workbench-detail example with the new summary/link blocks.
- Document the protected S67 routes in `contracts/openapi/nex-ag.openapi.yaml`.

## Contract Notes

- Evidence-link responses are metadata-safe refs, hashes, bounded previews,
  counts, timestamps, and links only.
- Action-admission responses are preflight-only and keep
  `POST /admin/v1/operator-review/cases/{case_id}/actions` authoritative.
- Workbench detail embeds only lightweight summaries and route links; it does
  not inline evidence items or admission items.

## Verification

```bash
./.venv/bin/python scripts/quality/validate_contracts.py contracts
./scripts/quality/run_quality_gate.sh
```

## Result

Contract validation covers 77 schemas, 112 positive examples, 82 negative
examples, and 7 OpenAPI files after adding the S67 examples.
