# Slice 0357: CX Remediation Execution Job Admission Wiring

## Scope

Wire accepted CX remediation execution requests to the service-local job queue
without changing the public remediation execution response contract.

This slice does not execute the worker, call MO, create child generation
records, add a database migration, perform PostgreSQL smoke testing, or call
remote providers.

## Implemented

- Added `cx.remediation_execution` as the service job type.
- Added deterministic remediation execution job ids based on
  `remediation_action_id`.
- Added `build_remediation_execution_job(...)`.
- Added `enqueue_remediation_execution_job(...)`.
- Added optional `job_queue` wiring to the CX remediation execution route.
- Wired the CX app to pass `SERVICE_PERSISTENCE.job_queue`.
- Job payloads include only raw-safe metadata:
  - remediation action id;
  - parent/root generation ids;
  - trace/request ids;
  - action/lineage type;
  - reason codes, source refs, and evidence hashes;
  - execution policy;
  - Slice 0356 worker plan.
- Job payloads exclude raw prompts, raw source text, raw model output,
  provider endpoints, credentials, model paths, and storage paths.
- Queue admission failures are returned as
  `cx.remediation_execution_job_admission_failed` problem responses.

## Refactoring Checkpoint

```text
external_api_changed=false
database_schema_changed=false
remote_provider_required=false
postgres_smoke_required=false
next_slice=0358_cx_remediation_execution_worker_mock_pipeline
```

## Evidence

Targeted regression:

```text
./.venv/bin/pytest tests/test_nex_cx_remediation_execution.py -q
15 passed, 1 warning in 0.48s

./.venv/bin/pytest tests/test_nex_cx_remediation_execution.py -q --cov=nex_cx.remediation_execution --cov-report=json:/tmp/cx_remediation_execution_cov_0357.json --cov-report=term-missing
15 passed, 1 warning in 1.11s
nex_cx.remediation_execution statement_coverage=100% branch_coverage=100%
```

Full quality gate:

```text
./scripts/quality/run_quality_gate.sh
2494 passed, 1 warning in 64.06s
statement_coverage=98.55% threshold=95.00%
branch_coverage=95.82% threshold=85.00%
contract_validation=pass schemas=59 examples=91 negative_examples=67 openapi=7
s34_feedback_disposition_closure=pass slice_range=0331-0340 required_files=21
s35_remediation_observability_closure=pass slice_range=0341-0350 required_files=26
```
