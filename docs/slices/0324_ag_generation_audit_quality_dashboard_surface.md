# Slice 0324: AG Generation Audit Quality Dashboard Surface

## Scope

Surface AG grounded response quality projection status in the operations
dashboard and issue-candidate workflow.

This slice does not add a database table, external provider call, or PostgreSQL
smoke. It adds an injectable dashboard section so later smoke/API work can feed
generation audit projections into AG operations without changing the dashboard
contract again.

## Implemented

- Added `generation_quality` to
  `ag_operations_dashboard_snapshot_projection.v1`.
- Added `ag_generation_quality_dashboard_section.v1` with:
  - summary counts by coverage status;
  - summary counts by boundary status;
  - recent generation quality items;
  - attention-only generation quality items.
- Added optional `generation_audit_projections` injection to dashboard and
  issue-candidate projection builders.
- Added `generation_quality_attention_required.v1` issue-candidate rule.
- Added issue candidate grouping for WARN, FAIL, and UNKNOWN quality statuses.
- Updated operations projection schema and dashboard fixture.

## Runtime Behavior

Default AG operations routes still return an empty generation quality section
because no persisted generation audit source is wired yet. Internal callers,
tests, and smoke runners can now pass generation audit projections and get a
dashboard-ready section.

The dashboard `projection_status` does not become `DEGRADED` solely because a
quality projection needs attention. Instead, attention is reported through the
issue-candidate workflow.

Recommended next slice:

```text
Slice 0325: AG generation audit quality smoke evidence
```

## Evidence

- Targeted operations regression:
  `./.venv/bin/pytest tests/test_nex_ag_operations.py -q`
- Contract validation:
  `./.venv/bin/pytest tests/test_contract_validation.py -q`
- Full quality gate:
  `./scripts/quality/run_quality_gate.sh`

Observed targeted operations result:

```text
147 passed, 1 warning
```

Observed targeted contract result:

```text
21 passed
```

Observed full quality gate result:

```text
2200 passed, 1 warning
statement_coverage=98.54%
branch_coverage=95.46%
contract_validation=pass schemas=51 examples=83 negative_examples=60 openapi=7
```
