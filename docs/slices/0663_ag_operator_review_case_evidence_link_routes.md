# Slice 0663: AG operator review case evidence-link route wiring

## Intent

Expose the Slice 0662 evidence-link read model through a protected AG route.

## Scope

- Add `GET /admin/v1/operator-review/cases/{case_id}/evidence-links`.
- Wire the route to `OperatorReviewCaseService.get_case_evidence_links(...)`.
- Allow `register_operator_review_case_routes(...)` to receive explicit
  operator-note and evidence-export stores for tests and local wiring.
- Keep the route before the generic case-detail route.
- Keep action-admission route wiring deferred to Slice 0665.

## Behavior

- The route requires the existing AG operator-review authorization boundary.
- It uses the case target ref to query matching `ag_op_notes` and
  `ag_ev_exports` records.
- It accepts the shared bounded `limit` query option.
- Missing cases return the existing `ag.operator_review_case_not_found`
  problem response.

## Privacy Guard

The route returns the same safe projection as Slice 0662: safe refs, hashes,
bounded previews, counts, statuses, timestamps, and detail paths only. It does
not expose raw notes, evidence bodies, action comments, prompts, source text,
storage paths, provider payloads, database URLs, tokens, idempotency keys, or
raw metadata payloads.

## Verification

```bash
./.venv/bin/pytest tests/test_nex_ag_operator_review_cases.py -q --cov=nex_ag.operator_review_cases --cov-branch --cov-report=term-missing
./scripts/quality/run_quality_gate.sh
```

## Result

The route-level regression covers authorization, missing-case handling, target
scoping, limit handling, route ordering ahead of generic detail lookup, and raw
payload leak prevention.
