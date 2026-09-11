# Slice 0647: AG Operator Review Case Operations Dashboard Wiring

Slice 0647 wires the AG operator review case/action rollup into the unified AG
operations dashboard.

## Scope

- Adds an `operator_review_cases` dashboard section to
  `ag_operations_dashboard_snapshot_projection.v1`.
- Passes the AG case store through `register_unified_operation_routes` and the
  `nex-ag` app wiring.
- Reuses the Slice 0646 case rollup metrics and operation time filtering.
- Reports case source status and degraded-source evidence when the case store is
  unavailable.
- Updates the operations projection schema and dashboard example for the new
  section.
- Keeps OpenAPI path documentation and protected PostgreSQL smoke evidence
  deferred to later S65 slices.

## Decision

- The dashboard section uses
  `ag_operator_review_case_dashboard_section.v1`.
- The dashboard exposes only counts, status/priority buckets, latest action
  type buckets, safe attention items, and redaction flags.
- Raw case comments, action comments, resolution text, prompts, generation
  output, source text, storage paths, and idempotency keys remain excluded.

## Verification

```bash
./.venv/bin/python -m py_compile services/nex-ag/nex_ag/operations.py services/nex-ag/nex_ag/main.py tests/test_nex_ag_operations.py
PYTHONPATH=services/_shared:services/nex-ag ./.venv/bin/pytest tests/test_nex_ag_operations.py tests/test_nex_ag_operator_review_cases.py -q
./.venv/bin/python scripts/quality/validate_contracts.py
./scripts/quality/run_quality_gate.sh
```
