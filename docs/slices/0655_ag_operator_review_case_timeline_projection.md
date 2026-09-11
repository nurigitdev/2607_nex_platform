# Slice 0655: AG Operator Review Case Timeline Projection

Slice 0655 connects the S66 case workbench detail to the AG operational event
history used by case creation and action routes.

## Scope

- Adds `GET /admin/v1/operator-review/cases/{case_id}/timeline`.
- Adds `ag_operator_review_case_timeline.v1`.
- Reuses the AG operational event store; no action-history table is added.
- Correlates only AG-owned case events:
  - `ag.operator_review_case.recorded`
  - `ag.operator_review_case_action.recorded`
- Returns metadata-only timeline items with event ids, event type, severity,
  message, timestamps, subject refs, safe case/action ids, status transitions,
  target refs, operator ids, assignee ids, counts, and comment/resolution
  hashes.
- Preserves the S65/S66 `operational_events_first` action-history policy.

## Decision

- Timeline reads are best-effort. If the event store is unavailable, the route
  returns `timeline_status=UNAVAILABLE` with a safe source error instead of
  exposing internals or failing the whole case workbench surface.
- Raw case comments, action comments, prompts, generated output, source text,
  storage paths, database URLs, service tokens, and idempotency keys remain out
  of the timeline payload.

## Verification

```bash
./.venv/bin/python -m py_compile services/nex-ag/nex_ag/operator_review_cases.py tests/test_nex_ag_operator_review_cases.py
PYTHONPATH=services/_shared:services/nex-ag ./.venv/bin/pytest tests/test_nex_ag_operator_review_cases.py -q --cov=nex_ag.operator_review_cases --cov-branch --cov-report=term-missing
./scripts/quality/run_quality_gate.sh
```
