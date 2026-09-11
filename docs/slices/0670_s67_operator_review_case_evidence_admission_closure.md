# Slice 0670: S67 operator review case evidence/admission closure

## Intent

Close the S67 operator-review case evidence/admission runtime integration work
after boundary audit, read models, protected routes, detail integration,
contracts, PostgreSQL smoke evidence, and privacy regression are in place.

## Scope

- Add
  `scripts/smoke/run_s67_operator_review_case_evidence_admission_closure.py`.
- Verify the Slice 0661-0670 documentation is contiguous.
- Verify the quality gate includes:
  - S67 boundary audit
  - S67 PostgreSQL smoke
  - S67 privacy regression
  - S67 closure checkpoint
- Verify S67 uses existing AG-owned persistence sources:
  - `ag_op_cases`
  - `ag_op_notes`
  - `ag_ev_exports`
- Verify contract/OpenAPI coverage for evidence-link and action-admission
  routes.

## Boundary

- Evidence-link payloads remain safe refs, hashes, bounded previews, counts,
  status fields, timestamps, redaction flags, and route links only.
- Action-admission remains preflight-only; the authoritative mutation route is
  still `POST /admin/v1/operator-review/cases/{case_id}/actions`.
- Workbench detail remains summary/link only and does not inline evidence items
  or action-admission items.
- No new table was introduced for S67.

## Evidence

```bash
./.venv/bin/python scripts/smoke/run_s67_operator_review_case_evidence_admission_closure.py --summary
```

Result:

```text
s67_operator_review_case_evidence_admission_closure=pass slice_range=0661-0670 required_files=33 boundary=ag_owned_operator_review_case_evidence_admission source_tables=ag_op_cases,ag_op_notes,ag_ev_exports smoke=test_db_evidence_admission privacy=route_surface_regression
```

## Verification

- Targeted closure tests with branch coverage.
- Full quality gate.
