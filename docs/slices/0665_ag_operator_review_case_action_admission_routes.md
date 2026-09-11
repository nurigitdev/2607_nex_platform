# Slice 0665: AG operator review case action-admission route wiring

## Intent

Expose the Slice 0664 action-admission preflight model through a protected AG
route.

## Scope

- Add `GET /admin/v1/operator-review/cases/{case_id}/action-admission`.
- Wire the route to `OperatorReviewCaseService.get_case_action_admission(...)`.
- Support optional `action_type` focus for one admission decision.
- Keep the route before the generic case-detail route.
- Keep the mutation route authoritative at
  `POST /admin/v1/operator-review/cases/{case_id}/actions`.

## Behavior

- The route requires the existing AG operator-review authorization boundary.
- Missing cases return the existing `ag.operator_review_case_not_found` problem
  response.
- Unsupported action types return
  `ag.operator_review_case_action_type_unsupported`.
- The response remains preflight-only and never performs a case mutation.

## Privacy Guard

The route returns state-machine metadata only. It excludes raw case comments,
raw action comments, raw resolution comments, prompts, generation output,
source text, storage paths, provider payloads, database URLs, tokens,
idempotency keys, and raw metadata payloads.

## Verification

```bash
./.venv/bin/pytest tests/test_nex_ag_operator_review_cases.py -q --cov=nex_ag.operator_review_cases --cov-branch --cov-report=term-missing
./scripts/quality/run_quality_gate.sh
```

## Result

Route-level regression covers authorization, missing-case handling, invalid
action type handling, focused admission decisions, route ordering, and raw
payload leak prevention.
