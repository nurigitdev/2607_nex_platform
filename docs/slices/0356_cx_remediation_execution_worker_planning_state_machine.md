# Slice 0356: CX Remediation Execution Worker Planning/State Machine

## Scope

Freeze the CX-side remediation execution worker plan and status transition
rules before adding job admission or executable worker code.

This slice is runtime-policy only. It does not enqueue jobs, call MO, run remote
providers, mutate generation records, add a public API, add a database
migration, or perform PostgreSQL smoke testing.

## Implemented

- Added `nex_cx.remediation_execution_planning`.
- Added the canonical CX remediation execution statuses:
  - `ACCEPTED`;
  - `RUNNING`;
  - `SUCCEEDED`;
  - `FAILED`;
  - `CANCELLED`.
- Added the allowed state machine:
  - `ACCEPTED -> RUNNING | CANCELLED`;
  - `RUNNING -> SUCCEEDED | FAILED | CANCELLED`;
  - terminal states do not transition further.
- Added action-specific worker planning for:
  - `retry_generation`;
  - `retrieval_repair`;
  - `citation_repair`.
- Worker plans freeze:
  - canonical `action_type -> lineage_type` mapping;
  - retrieval and prompt package policy;
  - parent generation immutability;
  - child repair generation creation on success;
  - `cx_to_mo_service_api_only` provider boundary;
  - raw prompt/evidence/output/provider-detail storage prohibition;
  - safe stage outputs limited to ids, hashes, refs, and statuses.
- Added transition helpers that produce safe record updates for:
  - start running;
  - success with a child repair generation id and result ref;
  - failure with a bounded safe failure payload;
  - cancellation with optional bounded safe failure payload.

## Refactoring Checkpoint

```text
external_api_changed=false
database_schema_changed=false
remote_provider_required=false
postgres_smoke_required=false
next_slice=0357_cx_remediation_execution_job_admission_wiring
```

## Evidence

Targeted regression:

```text
./.venv/bin/pytest tests/test_nex_cx_remediation_execution.py tests/test_nex_cx_remediation_execution_planning.py -q
47 passed, 1 warning in 0.49s

./.venv/bin/pytest tests/test_nex_cx_remediation_execution_planning.py -q --cov=nex_cx.remediation_execution_planning --cov-report=json:/tmp/cx_remediation_execution_planning_cov_0356.json --cov-report=term-missing
37 passed in 0.95s
nex_cx.remediation_execution_planning statement_coverage=100% branch_coverage=100%
```

Full quality gate:

```text
./scripts/quality/run_quality_gate.sh
2489 passed, 1 warning in 65.98s
statement_coverage=98.55% threshold=95.00%
branch_coverage=95.82% threshold=85.00%
contract_validation=pass schemas=59 examples=91 negative_examples=67 openapi=7
s34_feedback_disposition_closure=pass slice_range=0331-0340 required_files=21
s35_remediation_observability_closure=pass slice_range=0341-0350 required_files=26
```
