# Slice 0191: CX Processing Operations Dashboard Integration

## Scope

Slice 0191 integrates the CX processing run operations projection from Slices
0189-0190 into the AG operations dashboard snapshot and mock dashboard smoke.

Implemented:

- `cx_processing_runs` section in
  `ag_operations_dashboard_snapshot_projection.v1`
- dashboard summary for recent, failed, and active CX processing runs
- source-status/degraded-source handling for CX processing run operations
  sources
- `register_unified_operation_routes(..., cx_processing_run_stores=...)`
  wiring
- `nex-ag` app bootstrap wiring from the existing CX processing operations
  store
- mock-first AG operations dashboard smoke coverage for
  `/admin/v1/operations/cx-processing-runs` list/detail APIs
- operations projection schema/example update for the dashboard section
- CX processing persistence checkpoint status update to
  `ag_dashboard_integrated`

## Decision

The dashboard does not duplicate the full CX processing run detail projection.
It exposes a compact operator section:

- `summary`
- `recent`
- `recent_failures`
- `active`
- `source_statuses`

Each dashboard row includes ids, trace/request/job correlation, status, step
counts, timestamps, and `detail_path`. Raw source text, markdown, chunk text,
summary text, vectors, prompts, raw step output, and raw error details remain
outside the dashboard.

## Next Slice

Recommended next slice:

- `0192_cx_source_ownership_boundary_decision`

## Evidence

Targeted AG operations regression:

```bash
./.venv/bin/pytest tests/test_nex_ag_operations.py tests/test_smoke_helpers.py -q
```

Observed targeted result:

```text
274 passed
```

Extended targeted regression:

```bash
./.venv/bin/pytest tests/test_nex_ag_operations.py tests/test_smoke_helpers.py tests/test_contract_validation.py tests/test_nex_cx_processing_persistence.py tests/test_nex_cx_persistence_audit.py -q
```

Observed extended targeted result:

```text
300 passed
```

Contract regression:

```bash
./.venv/bin/pytest tests/test_contract_validation.py -q
./.venv/bin/python scripts/quality/validate_contracts.py
```

Observed contract result:

```text
16 passed
contract_validation=pass schemas=42 examples=71 negative_examples=49 openapi=7
```

Full quality gate:

```bash
./scripts/quality/run_quality_gate.sh
```

Observed full quality result:

```text
1455 passed
statement_coverage=98.03% threshold=95.00%
branch_coverage=93.49% threshold=85.00%
contract_validation=pass schemas=42 examples=71 negative_examples=49 openapi=7
ag_operations_dashboard_smoke=pass endpoints=20 jobs=2 workers=1 processing_runs=2 events=1 logs=1 history=1 issues=3
```
