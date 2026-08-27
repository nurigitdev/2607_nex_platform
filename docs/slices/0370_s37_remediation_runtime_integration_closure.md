# Slice 0370: S37 Remediation Runtime Integration Closure

## Scope

Close S37 by verifying that the remediation runtime integration path is present
and wired across CX execution, AG dispatch, CX read-model follow-up, AG status
sync, PostgreSQL smoke evidence, and the quality gate.

This slice does not add public API behavior, change database schema, call live
remote providers, or run a new repair worker implementation. It leaves behind a
closure guard so later slices cannot quietly drift away from the runtime
integration evidence established in S37.

## Implemented

- Added S37 closure checker:
  - `scripts/smoke/run_s37_remediation_runtime_integration_closure.py`.
- Checked required files across:
  - CX remediation execution API/runtime;
  - CX remediation execution worker batch runtime;
  - AG-to-CX dispatch and status-sync runtime;
  - AG and CX OpenAPI contracts;
  - guarded PostgreSQL smoke runners for CX execution, AG dispatch, CX
    read-model, and AG status sync;
  - optional PostgreSQL smoke suite stage wiring;
  - S37 slice docs from `0361` through `0370`.
- Registered the closure checker in the full quality gate.
- Added regression coverage for pass, missing-file, token-failure, summary, and
  JSON CLI paths.

## Refactoring Checkpoint

```text
external_api_changed=false
database_schema_changed=false
remote_provider_required=false
postgres_smoke_required=false
s37_closure_status=pass
slice_range=0361-0370
next_slice=0371_review_next_increment
```

## Evidence

Targeted regression:

```text
./.venv/bin/pytest tests/test_s37_remediation_runtime_integration_closure.py -q --cov=run_s37_remediation_runtime_integration_closure --cov-report=term-missing --cov-report=json:/tmp/s37_closure_cov_0370.json
4 passed in 0.08s
scripts/smoke/run_s37_remediation_runtime_integration_closure.py statement_coverage=100% branch_coverage=100%
```

Closure smoke:

```text
./.venv/bin/python scripts/smoke/run_s37_remediation_runtime_integration_closure.py --summary
s37_remediation_runtime_integration_closure=pass slice_range=0361-0370 required_files=31
```

Full quality gate:

```text
./scripts/quality/run_quality_gate.sh
2620 passed, 1 warning in 66.95s
statement_coverage=98.60% threshold=95.00%
branch_coverage=95.92% threshold=85.00%
contract_validation=pass schemas=59 examples=91 negative_examples=67 openapi=7
s34_feedback_disposition_closure=pass slice_range=0331-0340 required_files=21
s35_remediation_observability_closure=pass slice_range=0341-0350 required_files=26
s36_remediation_execution_closure=pass slice_range=0351-0360 required_files=33
s37_remediation_runtime_integration_closure=pass slice_range=0361-0370 required_files=31
```
