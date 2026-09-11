# Slice 0652: AG Operator Review Case Queue Read Model

Slice 0652 adds the first S66 read model: an operator-facing case queue
projection built from existing AG-owned case records.

## Scope

- Adds `GET /admin/v1/operator-review/cases/queue`.
- Adds `ag_operator_review_case_queue.v1` projection output.
- Reuses the existing protected AG operator-review auth boundary.
- Reuses `ag_op_cases` and the existing case list filters; no database table is
  added.
- Converts case records into safe queue items with target refs, operator refs,
  assignment refs, attention status, recommended actions, latest safe action
  summary, and case/detail/action links.
- Keeps raw case comments, raw action comments, raw resolution text, raw
  prompts, source text, generation output, storage paths, and idempotency keys
  out of the queue payload.

## Decision

- The queue is read-model-first and remains separate from case mutation logic.
- Default queue ordering prioritizes `BLOCKED`, then `ATTENTION`, then `OPEN`,
  then `OK`; within each group, recently updated cases appear first.
- Filter/search/sort hardening remains deferred to Slice 0653.
- Timeline and evidence-link projections remain deferred to later S66 slices.

## Verification

```bash
./.venv/bin/python -m py_compile services/nex-ag/nex_ag/operator_review_cases.py tests/test_nex_ag_operator_review_cases.py
PYTHONPATH=services/_shared:services/nex-ag ./.venv/bin/pytest tests/test_nex_ag_operator_review_cases.py -q --cov=nex_ag.operator_review_cases --cov-branch --cov-report=term-missing
./scripts/quality/run_quality_gate.sh
```
