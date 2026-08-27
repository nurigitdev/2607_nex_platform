# Slice 0375: AG Remediation Execution Status Sync Job Planning Foundation

## Scope

Add the AG-side planning foundation for queueing remediation execution status
sync as a service-local background job.

This slice does not add a public API route, change database schema, run
PostgreSQL smoke evidence, execute a worker, or call remote providers. It keeps
the existing Slice 0368/0369 synchronous status-sync facade as the execution
boundary and prepares a deterministic `common_job.v1` payload that Slice 0376
can run through the shared worker/job-control path.

## Implemented

- Added `nex_ag.remediation_execution_status_sync_jobs`.
- Added deterministic job planning for AG remediation execution operations with
  `status_sync_state=SYNC_REQUIRED`.
- Added skip/block decisions for:
  - records that do not require attention;
  - non-actionable sync states;
  - operator-review states such as `NO_EXECUTION`, `ORPHAN_EXECUTION`,
    `TERMINAL_TASK_DIVERGED`, and `UNKNOWN_EXECUTION_STATUS`;
  - missing runtime correlation fields.
- Built the queued job with the shared `common_job.v1` shape, deterministic
  `job_id`, AG-scoped idempotency key, subject ref, retry metadata, and safe
  AG/CX debug links.
- Added a redaction guard that rejects raw prompt/output/source/evidence fields,
  provider details, credentials, database URLs, tokens, and storage paths while
  allowing explicit redaction-summary false flags.
- Covered optional value normalization, safe failure summaries, invalid input
  errors, deterministic identifiers, and redaction branches.

## Refactoring Checkpoint

```text
external_api_changed=false
database_schema_changed=false
remote_provider_required=false
postgres_smoke_required=false
worker_runtime_changed=false
next_slice=0376_ag_remediation_execution_status_sync_worker_mock_runtime
```

## Evidence

Targeted regression:

```text
./.venv/bin/pytest tests/test_nex_ag_remediation_execution_status_sync_jobs.py -q --cov=nex_ag.remediation_execution_status_sync_jobs --cov-branch --cov-report=term-missing
13 passed in 0.87s
services/nex-ag/nex_ag/remediation_execution_status_sync_jobs.py statement_coverage=100% branch_coverage=100%
```

Full quality gate:

```text
./scripts/quality/run_quality_gate.sh
2672 passed, 1 warning in 85.11s
statement_coverage=98.61% threshold=95.00%
branch_coverage=95.92% threshold=85.00%
contract_validation=pass schemas=59 examples=91 negative_examples=67 openapi=7
ag_operations_dashboard_smoke=pass endpoints=20 jobs=2 workers=1 processing_runs=2 threshold_decisions=2 events=1 logs=1 history=1 issues=4
s34_feedback_disposition_closure=pass slice_range=0331-0340 required_files=21
s35_remediation_observability_closure=pass slice_range=0341-0350 required_files=26
s36_remediation_execution_closure=pass slice_range=0351-0360 required_files=33
s37_remediation_runtime_integration_closure=pass slice_range=0361-0370 required_files=31
```
