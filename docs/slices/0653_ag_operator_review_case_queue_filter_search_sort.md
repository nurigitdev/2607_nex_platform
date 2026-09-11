# Slice 0653: AG Operator Review Case Queue Filter/Search/Sort

Slice 0653 hardens the S66 operator-facing case queue controls without adding a
new persistence boundary.

## Scope

- Extends `GET /admin/v1/operator-review/cases/queue` with queue-specific
  controls:
  - `latest_action_type`
  - `attention_status`
  - `q`
  - `sort_by`
  - `sort_direction`
- Keeps the existing AG-owned case filters from Slice 0652.
- Adds explicit allow-lists for attention status, sort fields, and sort
  directions.
- Returns normalized `filters` and `sort` metadata in
  `ag_operator_review_case_queue.v1`.
- Searches only safe queue fields: ids, statuses, priorities, safe refs, reason
  codes, recommended actions, safe latest-action metadata, resolution hash, and
  bounded resolution preview.

## Decision

- Queue filtering/search/sort stays in the projection layer for now. The source
  record list remains backed by the existing `ag_op_cases` filters, so this
  slice adds no table, migration, or PostgreSQL smoke script.
- Invalid queue control values fail fast with `problem+json` errors before
  returning a partial queue.
- Default ordering remains attention-first: `BLOCKED`, `ATTENTION`, `OPEN`,
  then `OK`, with recent updates first inside each group.

## Verification

```bash
./.venv/bin/python -m py_compile services/nex-ag/nex_ag/operator_review_cases.py tests/test_nex_ag_operator_review_cases.py
PYTHONPATH=services/_shared:services/nex-ag ./.venv/bin/pytest tests/test_nex_ag_operator_review_cases.py -q --cov=nex_ag.operator_review_cases --cov-branch --cov-report=term-missing
./scripts/quality/run_quality_gate.sh
```
