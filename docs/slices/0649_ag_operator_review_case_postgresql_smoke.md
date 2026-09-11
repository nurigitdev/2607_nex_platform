# Slice 0649: AG Operator Review Case PostgreSQL Smoke Evidence

## Intent

Add protected PostgreSQL smoke evidence for the AG-owned operator review
case/action loop before S65 closure.

## Scope

- Add `scripts/smoke/run_ag_operator_review_case_postgres_smoke.py`.
- Run AG migrations against the selected test profile before smoke execution.
- Create a case through the protected route, replay the idempotent create, apply
  an assignment action, read detail/list/rollup/dashboard projections, inspect
  `ag_op_cases` directly, and clean up the smoke row.
- Keep default quality-gate behavior safe by skipping unless
  `NEX_AG_OPERATOR_REVIEW_CASE_POSTGRES_SMOKE=1`.

## Evidence Boundary

- The smoke evidence records the redacted database URL only.
- Raw action comments and raw idempotency keys are rejected by the evidence
  redaction guard.
- Action history remains operational-event-first; `ag_op_cases` only stores the
  safe latest action summary in metadata.

## Verification

- Targeted smoke regression tests.
- Protected live PostgreSQL smoke against `nex_ag_test`.
- Full quality gate.
