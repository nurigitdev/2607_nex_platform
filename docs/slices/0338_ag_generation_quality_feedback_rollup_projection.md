# Slice 0338: AG Generation Quality Feedback Rollup Projection

## Scope

Create a safe AG projection that combines generation quality signals, AE user
feedback, and AG operator dispositions into one operator-facing rollup.

## Implemented

- Added `ag_generation_quality_feedback_rollup.v1` projection builder.
- Grouped signals by `cx_generation_id` across:
  - AG generation quality dashboard/detail items;
  - AE generation feedback records;
  - AG operator disposition records.
- Added attention-state derivation:
  - `OPEN`;
  - `IN_PROGRESS`;
  - `CLOSED`;
  - `OK`.
- Added summary counters for feedback, negative feedback, dispositions, open
  attention, closed attention, and unlinked feedback.
- Added recommended operator actions for common states:
  - record disposition;
  - continue disposition;
  - follow escalation;
  - fetch generation quality detail;
  - monitor closed disposition.
- Added contract schema, positive example, and negative raw-output example.
- Ensured the rollup does not copy raw prompts, raw generated output, feedback
  comment previews, or operator note previews.

## Evidence

Targeted regression:

```text
./.venv/bin/pytest tests/test_nex_ag_generation_quality_feedback_rollup.py -q
10 passed in 0.06s
```

Contract validation:

```text
./.venv/bin/python scripts/quality/validate_contracts.py
contract_validation=pass schemas=55 examples=87 negative_examples=64 openapi=7
```

No PostgreSQL smoke is attached to this slice because it is a pure projection
foundation over already-tested input stores.
