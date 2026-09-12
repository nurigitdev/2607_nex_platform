# Slice 0674: AG operator review case assignment workload projection

## Intent

Add assignment/status workload signals for the S68 decision lifecycle without
introducing a new persistence table.

## Scope

- Add `ag_operator_review_case_assignment_workload.v1` as an internal read-model
  schema version constant.
- Group case list records by `assignment_ref`.
- Preserve an explicit unassigned group for open cases that still need ownership.
- Summarize open, closed, urgent, attention, blocked, actioned, status, priority,
  and latest-action counts.
- Keep the projection safe for dashboard and operator workbench reuse.

## Decision

The workload projection is derived from `ag_op_cases` rows already available via
the case list read model. It does not create a new table and does not copy raw
case comments, action comments, resolution text, idempotency keys, raw metadata,
provider payloads, storage paths, database URLs, or tokens.

## Verification

```bash
./.venv/bin/python -m py_compile services/nex-ag/nex_ag/operator_review_cases.py tests/test_nex_ag_operator_review_cases.py
PYTHONPATH=services/_shared:services/nex-ag ./.venv/bin/pytest tests/test_nex_ag_operator_review_cases.py -q --cov=nex_ag.operator_review_cases --cov-branch --cov-report=term-missing
```

## Result

The targeted tests cover assigned and unassigned workload groups, urgent
attention counts, latest-action aggregation, service wrapper wiring, and raw
payload redaction.
