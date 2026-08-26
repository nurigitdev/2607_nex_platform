# Slice 0355: CX Repair Attempt Lineage Persistence Foundation

## Scope

Persist CX remediation execution attempts as lineage metadata without storing
raw prompts, source text, model output, provider endpoints, or credentials.

This slice keeps the Slice 0354 public API response contract unchanged. The
database row adds operational lineage fields such as `root_cx_generation_id`,
`attempt_no`, and internal `metadata` so future repair execution and AG
debugging can query parent, root, status, trace, and child repair generation
links efficiently.

This slice does not execute MO generation, create child generation records,
perform PostgreSQL smoke testing, or call remote providers.

## Implemented

- Added `0355_cx_repair_attempt_lineage_persistence_foundation.sql`.
- Added `cx_remediation_execution_attempts` with:
  - immutable parent/repair generation separation;
  - canonical `action_type -> lineage_type` checks;
  - accepted/running/terminal status persistence fields;
  - JSONB references for `result_ref`, `failure`, redaction summary, and
    internal metadata;
  - parent/root/status/trace/repair-generation indexes for AG and CX
    operations queries.
- Added `SqlAlchemyRemediationExecutionStore`.
- Wired CX `main.py` to use the SQLAlchemy store when PostgreSQL persistence is
  enabled, while leaving the fast in-memory regression path as the default.
- Added SQLite regression coverage for save/get/list/upsert reindexing and DB
  unavailability mapping.
- Added migration structure checks that explicitly reject raw/provider payload
  columns.

## Refactoring Checkpoint

```text
external_api_changed=false
database_schema_changed=true
remote_provider_required=false
postgres_smoke_required=false
next_slice=0356_cx_remediation_execution_worker_planning
```

## Evidence

Targeted regression:

```text
./.venv/bin/pytest tests/test_nex_cx_remediation_execution.py tests/test_database_schema_foundation.py -q
28 passed, 1 warning in 0.52s

./.venv/bin/pytest tests/test_nex_cx_remediation_execution.py -q --cov=nex_cx.remediation_execution --cov-report=json:/tmp/cx_remediation_execution_cov_0355.json --cov-report=term-missing
10 passed, 1 warning in 1.06s
nex_cx.remediation_execution statement_coverage=100% branch_coverage=100%
```

Full quality gate:

```text
./scripts/quality/run_quality_gate.sh
2452 passed, 1 warning in 68.62s
statement_coverage=98.54% threshold=95.00%
branch_coverage=95.78% threshold=85.00%
contract_validation=pass schemas=59 examples=91 negative_examples=67 openapi=7
s34_feedback_disposition_closure=pass slice_range=0331-0340 required_files=21
s35_remediation_observability_closure=pass slice_range=0341-0350 required_files=26
```
