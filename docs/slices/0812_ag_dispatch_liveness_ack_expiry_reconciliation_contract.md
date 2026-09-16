# Slice 0812: AG dispatch liveness acknowledgement expiry reconciliation contract

## Objective

Define the deterministic S82 candidate and transition contract before adding
database candidate selection or mutation.

## Changes

- Added an expiry candidate projection with `ELIGIBLE` and `SKIPPED` outcomes.
- Fixed the eligibility rule to stored `SUPPRESSED` state with
  `suppressed_until <= observed_at`.
- Added safe skip reasons for missing state, non-suppressed state, missing
  deadline, and active suppression.
- Added a pure transition that produces an `EXPIRED` copy and preserves the
  original state for compare-and-set persistence in Slice 0813.
- Recorded only safe reconciliation metadata; source liveness and raw payloads
  remain outside this contract.

## Guardrails

- No route, table, query, or database mutation is added in this slice.
- The input record is never modified in place.
- Persistence must compare the expected stored status and `updated_at` value
  before applying the transition.

## Verification

```bash
./.venv/bin/pytest tests/test_nex_ag_operator_review_liveness_ack_expiry.py tests/test_nex_ag_operator_review_liveness_ack.py -q --tb=short
```

Result: `25 passed`; `operator_review_liveness_ack.py` statement/branch
coverage `100%`.

Full regression result: `5367 passed, 1 warning`.

- Statement coverage: `68816 / 69699 = 98.733123861174%`.
- Branch coverage: `16349 / 17000 = 96.170588235294%`.
