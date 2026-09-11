# Slice 0669: AG operator review case evidence/admission privacy regression

## Intent

Lock the S67 evidence-link and action-admission privacy boundary after the
contract and PostgreSQL smoke surfaces are in place.

## Scope

- Add
  `scripts/smoke/run_ag_operator_review_case_evidence_admission_privacy_regression.py`.
- Build a mock-first unsafe fixture that deliberately injects raw operator
  notes, raw evidence bodies, raw action/resolution comments, raw prompts,
  source text, storage paths, provider keys, service tokens, database URLs, and
  idempotency keys into case, note, and export records.
- Drive protected AG routes for:
  - `GET /admin/v1/operator-review/cases/{case_id}/workbench-detail`
  - `GET /admin/v1/operator-review/cases/{case_id}/evidence-links`
  - `GET /admin/v1/operator-review/cases/{case_id}/action-admission?action_type=RESOLVE`
- Verify public payloads expose only safe refs, hashes, bounded previews,
  summary counts, state-machine admission metadata, redaction flags, and route
  links.

## Boundary

- No database migration or new table.
- No live PostgreSQL dependency; this is a deterministic in-memory regression.
- Workbench detail remains summary/link only and does not inline evidence items
  or action admission items.
- Evidence-link and action-admission routes remain authoritative for full S67
  preflight detail.

## Evidence

```bash
./.venv/bin/python scripts/smoke/run_ag_operator_review_case_evidence_admission_privacy_regression.py --summary
```

Result:

```text
ag_operator_review_case_evidence_admission_privacy_regression=pass surfaces=3 forbidden_labels=11
```

## Verification

- Targeted privacy regression tests with branch coverage.
- Full quality gate.
