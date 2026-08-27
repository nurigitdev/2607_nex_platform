# Slice 0371: Remediation Runtime Operations Gap Audit

## Scope

Start S38 by freezing the remaining AG operations gaps after S37 proved the
remediation runtime path across CX execution, AG dispatch, CX read-model
follow-up, AG status sync, and guarded PostgreSQL smoke evidence.

This slice does not add a public API, database schema, PostgreSQL smoke runner,
remote provider call, or background worker. It records the next runtime
operations boundaries before AG exposes execution operations projections and
status-sync automation.

## Boundary Decision

- AG owns operator-facing remediation execution operations, issue candidates,
  and status-sync scheduling.
- CX owns remediation execution attempts and repair lineage records.
- AG operations projections are read-only against CX execution records.
- AG may update only its own remediation task state through the existing
  status-sync facade.
- CX must not mutate AG task records.
- Remote providers are not required for S38 operations slices `0371` through
  `0377`; mock/runtime state is sufficient until live repair generation
  execution is introduced.

## Implemented

- Added `ag_remediation_runtime_operations_gap_audit.v1`.
- Recorded closed S37 capabilities from:
  - CX remediation execution contract/API/worker;
  - AG remediation dispatch API and PostgreSQL smoke;
  - CX remediation execution read-model API and PostgreSQL smoke;
  - AG remediation execution status-sync API;
  - S37 closure evidence.
- Recorded the next operations gaps:
  - `0372` AG remediation execution operations projection;
  - `0373` AG remediation execution operations API;
  - `0374` AG dashboard and issue-candidate integration;
  - `0375` AG status-sync job plan;
  - `0376` AG status-sync worker runtime;
  - `0377` AG status-sync PostgreSQL smoke evidence.
- Added a safe debug contract that rejects database URLs, service tokens,
  provider API keys, raw prompts, raw generation outputs, raw source text, and
  raw evidence values.

## Refactoring Checkpoint

```text
external_api_changed=false
database_schema_changed=false
remote_provider_required=false
postgres_smoke_required=false
next_slice=0372_ag_remediation_execution_operations_projection_foundation
```

## Evidence

Targeted regression:

```text
./.venv/bin/pytest tests/test_nex_ag_remediation_runtime_audit.py -q --cov=nex_ag.remediation_runtime_audit --cov-report=term-missing --cov-report=json:/tmp/ag_remediation_runtime_audit_0371_cov.json
17 passed in 0.12s
services/nex-ag/nex_ag/remediation_runtime_audit.py statement_coverage=100% branch_coverage=100%
```

Full quality gate:

```text
./scripts/quality/run_quality_gate.sh
2637 passed, 1 warning in 70.19s
statement_coverage=98.61% threshold=95.00%
branch_coverage=95.94% threshold=85.00%
contract_validation=pass schemas=59 examples=91 negative_examples=67 openapi=7
s34_feedback_disposition_closure=pass slice_range=0331-0340 required_files=21
s35_remediation_observability_closure=pass slice_range=0341-0350 required_files=26
s36_remediation_execution_closure=pass slice_range=0351-0360 required_files=33
s37_remediation_runtime_integration_closure=pass slice_range=0361-0370 required_files=31
```
