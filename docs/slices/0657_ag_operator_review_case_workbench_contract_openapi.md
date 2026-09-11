# Slice 0657: AG operator review case workbench contract/OpenAPI hardening

## Scope

- Adds `operator_review_case_workbench.v1.schema.json` for the S66 case
  workbench surfaces:
  - `ag_operator_review_case_queue.v1`
  - `ag_operator_review_case_workbench_detail.v1`
  - `ag_operator_review_case_timeline.v1`
- Adds positive contract fixtures for queue, workbench detail, and timeline.
- Adds negative contract fixtures that reject raw action/resolution comment
  leakage on the queue, detail, and timeline surfaces.
- Extends `contracts/openapi/nex-ag.openapi.yaml` with:
  - `GET /admin/v1/operator-review/cases/queue`
  - `GET /admin/v1/operator-review/cases/{case_id}/workbench-detail`
  - `GET /admin/v1/operator-review/cases/{case_id}/timeline`

## Boundary

- No runtime or database schema change.
- The schema intentionally allows only metadata-safe refs, hashes, bounded
  previews, action controls, route links, and operational-event metadata.
- Raw comments, prompts, source text, storage paths, and idempotency keys remain
  forbidden by `additionalProperties: false` and redaction constants.

## Evidence

```bash
./.venv/bin/python scripts/quality/validate_contracts.py
```

Result:

```text
contract_validation=pass schemas=77 examples=110 negative_examples=82 openapi=7
```

## Next

- Slice 0658 should add guarded PostgreSQL smoke evidence for the case
  workbench queue/detail/timeline surfaces against `nex_ag_test`.
