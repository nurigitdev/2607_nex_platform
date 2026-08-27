# Slice 0383: AE Repaired Handoff Persistence Foundation

## Scope

Add the AE persistence foundation for repaired response handoff records.

This slice does not register public routes or run PostgreSQL smoke yet. It adds
the storage API, SQLite regression proof, and PostgreSQL migration that Slice
0384/0385 will use.

## Implemented

- Added in-memory `RepairedResponseHandoffStore`.
- Added `SqlAlchemyRepairedResponseHandoffStore` with:
  - `save`;
  - `get`;
  - `list_for_interaction`;
  - `delete` for smoke cleanup and regression hygiene.
- Added `default_repaired_response_handoff_store(app)` so AE can use
  `app.state.nex_persistence.api_session_factory` when runtime persistence is
  bootstrapped.
- Added migration
  `database/nex-ae-api/migrations/0383_ae_repaired_response_handoff_persistence.sql`.
- Stored only safe handoff records: ids, ownership scope, CX lineage refs,
  hashes, short preview, usage metadata, user-surface hints, links, redaction
  flags, and trace/request metadata.
- Added owner, interaction, parent generation, repair generation, and
  remediation action indexes for operational lookup.

## Evidence

Targeted regression:

```text
./.venv/bin/pytest tests/test_nex_ae_repaired_responses.py -q
26 passed in 1.03s
```

Targeted persistence coverage:

```text
./.venv/bin/pytest tests/test_nex_ae_repaired_responses.py -q --cov=nex_ae_api.repaired_responses --cov-branch --cov-report=term-missing
services/nex-ae-api/nex_ae_api/repaired_responses.py statement_coverage=100% branch_coverage=100%
```

Full quality gate:

```text
scripts/quality/run_quality_gate.sh
2775 passed, 1 warning in 77.30s
statement_coverage=98.65% threshold=95.00%
branch_coverage=96.04% threshold=85.00%
contract_validation=pass schemas=60 examples=92 negative_examples=68 openapi=7
s34_feedback_disposition_closure=pass slice_range=0331-0340 required_files=21
s35_remediation_observability_closure=pass slice_range=0341-0350 required_files=26
s36_remediation_execution_closure=pass slice_range=0351-0360 required_files=33
s37_remediation_runtime_integration_closure=pass slice_range=0361-0370 required_files=31
s38_remediation_operations_automation_closure=pass slice_range=0371-0380 required_files=41
```

Recommended next slices:

```text
Slice 0384: AE repaired handoff service API wiring
Slice 0385: AE repaired handoff PostgreSQL smoke evidence
```
