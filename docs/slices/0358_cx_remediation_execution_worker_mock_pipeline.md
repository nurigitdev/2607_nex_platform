# Slice 0358: CX Remediation Execution Worker Mock Pipeline

## Scope

Add a deterministic CX remediation execution worker path without calling MO or
remote providers.

This slice does not add a public API route, change database schema, perform
PostgreSQL smoke testing, or call live embedding/reranker/generation providers.

## Implemented

- Added `nex_cx.remediation_execution_worker`.
- Added `run_remediation_execution_worker_once(...)`.
- Added `execute_claimed_remediation_execution_job(...)` for future shared
  worker-runner integration.
- Added `build_remediation_execution_worker_handler(...)` so the same handler
  can be used by a runner that already claimed a job.
- Worker behavior:
  - claims only `cx.remediation_execution` jobs;
  - loads the remediation execution record by `remediation_action_id`;
  - transitions `ACCEPTED -> RUNNING -> SUCCEEDED` on success;
  - resumes records that are already `RUNNING`;
  - creates a deterministic child repair generation record;
  - persists a canonical `repair_execution` result ref;
  - marks jobs `SUCCEEDED` or `FAILED`;
  - leaves parent generation records unchanged.
- Failure behavior:
  - missing execution record fails the job without creating a repair record;
  - missing/mismatched parent generation fails the execution record and job;
  - invalid persisted execution shape fails the job without rewriting the
    invalid execution row;
  - terminal execution records are not rewritten by the worker.
- Mock repair generation records store only ids, lineage, hashes/refs/status
  metadata, and redaction flags. They do not store raw prompts, source text,
  evidence text, provider endpoints, credentials, or model paths.

## Refactoring Checkpoint

```text
external_api_changed=false
database_schema_changed=false
remote_provider_required=false
postgres_smoke_required=false
parent_generation_mutation_allowed=false
next_slice=0359_cx_remediation_execution_runner_integration
```

## Evidence

Targeted regression:

```text
./.venv/bin/pytest tests/test_nex_cx_remediation_execution_worker.py -q
14 passed in 0.51s

./.venv/bin/pytest tests/test_nex_cx_remediation_execution_worker.py -q --cov=nex_cx.remediation_execution_worker --cov-report=json:/tmp/cx_remediation_execution_worker_cov_0358.json --cov-report=term-missing
14 passed in 0.93s
nex_cx.remediation_execution_worker statement_coverage=100% branch_coverage=100%

./.venv/bin/pytest tests/test_nex_cx_remediation_execution.py tests/test_nex_cx_remediation_execution_planning.py tests/test_nex_cx_remediation_execution_worker.py -q
66 passed, 1 warning in 0.53s
```

Full quality gate:

```text
./scripts/quality/run_quality_gate.sh
2508 passed, 1 warning in 67.31s
statement_coverage=98.55% threshold=95.00%
branch_coverage=95.84% threshold=85.00%
contract_validation=pass schemas=59 examples=91 negative_examples=67 openapi=7
s34_feedback_disposition_closure=pass slice_range=0331-0340 required_files=21
s35_remediation_observability_closure=pass slice_range=0341-0350 required_files=26
```
