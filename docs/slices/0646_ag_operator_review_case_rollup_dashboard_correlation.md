# Slice 0646: AG Operator Review Case Rollup Dashboard Correlation

Slice 0646 adds a redaction-safe case/action rollup for AG operator review
dashboard correlation.

## Scope

- Adds `GET /admin/v1/operator-review/cases/rollups`.
- Reuses the existing protected AG operator-review auth boundary.
- Reuses case list filters so dashboard views can scope by target, status,
  priority, operator, assignee, trace, and update window.
- Correlates case status, priority, assignment, and the latest action summary
  into attention metrics.
- Keeps raw case comments, raw action comments, raw resolution text,
  idempotency keys, prompts, source text, generation output, and storage paths
  out of the rollup payload.
- Keeps OpenAPI/schema freeze and PostgreSQL smoke evidence deferred to later
  S65 slices.

## Decision

- The rollup route follows the existing workbench `/rollups` route pattern.
- Latest action history remains operational-event-first; the rollup only uses
  the redaction-safe `metadata.last_action` summary already stored with the
  case record.
- `URGENT` non-closed cases are surfaced as `BLOCKED`; reopened cases are
  surfaced as `ATTENTION`; other open or in-progress cases are surfaced as
  `OPEN`.

## Verification

```bash
./.venv/bin/python -m py_compile services/nex-ag/nex_ag/operator_review_cases.py tests/test_nex_ag_operator_review_cases.py
PYTHONPATH=services/_shared:services/nex-ag ./.venv/bin/pytest tests/test_nex_ag_operator_review_cases.py -q --cov=nex_ag.operator_review_cases --cov-branch --cov-report=term-missing
./scripts/quality/run_quality_gate.sh
```
