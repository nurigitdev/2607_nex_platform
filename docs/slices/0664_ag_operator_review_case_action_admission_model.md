# Slice 0664: AG operator review case action-admission decision model

## Intent

Add a read-only action-admission preflight model for operator review cases before
exposing the route.

## Scope

- Add `ag_operator_review_case_action_admission.v1`.
- Add `OperatorReviewCaseService.get_case_action_admission(...)`.
- Add `build_operator_review_case_action_admission_projection(...)`.
- Reuse the existing case action state-machine tables:
  - `CASE_ACTION_ALLOWED_FROM`
  - `CASE_ACTION_TARGET_STATUSES`
- Keep the mutation route authoritative at
  `POST /admin/v1/operator-review/cases/{case_id}/actions`.
- Keep protected route wiring deferred to Slice 0665.

## Behavior

The projection can list all preflight decisions or focus on one requested
`action_type`. Each item includes the current status, target status, admission
result, blocked reason, required idempotency key flag, assignment requirement,
resolution-comment requirement, mutation method, and mutation path.

## Privacy Guard

The model is case-state-machine metadata only. It excludes raw case comments,
raw action comments, raw resolution comments, prompts, generation output, source
text, storage paths, provider payloads, database URLs, tokens, idempotency keys,
and raw metadata payloads.

## Verification

```bash
./.venv/bin/pytest tests/test_nex_ag_operator_review_cases.py -q --cov=nex_ag.operator_review_cases --cov-branch --cov-report=term-missing
./scripts/quality/run_quality_gate.sh
```

## Result

Regression coverage confirms open-case admission, closed-case blocking,
requested-action focus, invalid action type rejection, service wiring, and raw
metadata leak prevention.
