# Slice 0673: AG operator review case action outcome read model

## Intent

Add a reusable, redaction-safe action outcome read model for the S68 operator
review case decision lifecycle work.

## Scope

- Add `ag_operator_review_case_action_outcomes.v1` as an internal read-model
  schema version constant.
- Derive action outcomes from the hardened case timeline projection.
- Keep action history `operational_events_first`; no action-history or
  lifecycle table is introduced.
- Summarize status transitions, assignment actions, terminal actions, and
  resolution-recorded actions.
- Preserve deterministic timeline sequence values so clients can correlate
  action outcomes back to timeline items.
- Keep raw event details, raw comments, resolution text, idempotency keys,
  metadata payloads, provider payloads, storage paths, database URLs, and tokens
  out of the read model.

## Decision

Slice 0673 keeps the action outcome surface read-model-only. The authoritative
mutation route remains
`POST /admin/v1/operator-review/cases/{case_id}/actions`, and the action outcome
projection consumes the safe timeline item payload rather than raw operational
event details.

## Verification

```bash
./.venv/bin/python -m py_compile services/nex-ag/nex_ag/operator_review_cases.py tests/test_nex_ag_operator_review_cases.py
PYTHONPATH=services/_shared:services/nex-ag ./.venv/bin/pytest tests/test_nex_ag_operator_review_cases.py -q --cov=nex_ag.operator_review_cases --cov-branch --cov-report=term-missing
```

## Result

The targeted tests cover assignment and terminal action outcomes, limited
timeline windows, unavailable event stores, and raw payload redaction.
