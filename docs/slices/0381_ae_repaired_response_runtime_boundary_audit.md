# Slice 0381: AE Repaired Response Runtime Boundary Audit

## Scope

Start S39 by freezing the AE runtime boundary for presenting CX repaired
generation results back to a chat user.

This slice does not add a route, database migration, PostgreSQL smoke, remote
provider call, or user decision workflow. It records the ownership, source,
storage, mutation, and next-slice rules that the repaired response runtime must
follow before adapter, persistence, and API wiring are added.

## Boundary Decision

- AE API owns the repaired response handoff system of record.
- AE Web owns the user-visible repaired response review surface.
- CX remains the source of remediation execution detail, repaired generation
  lineage, and repaired generation execution records.
- AG remains the remediation task orchestration owner.
- AE accepts only:
  - `cx_remediation_execution_detail.v1` details;
  - `cx_repaired_generation_lineage.v1` records with `LINKED` status;
  - `cx_generation_execution_record.v1` repaired records with `COMPLETED`
    status;
  - `SUCCEEDED` remediation executions with consistent lineage and no parent
    generation mutation.
- AE stores only ids, refs, hashes, short previews, usage metadata, quality
  summaries, user surface hints, links, redaction flags, and trace/request
  metadata.
- AE must not store raw prompt text, raw generation output, raw source text,
  raw evidence, provider endpoints, credentials, database URLs, storage paths,
  model paths, or local filesystem paths.

## Refactoring Checkpoint

```text
external_api_changed=false
database_schema_changed=false
remote_provider_required=false
postgres_smoke_required=false
runtime_route_changed=false
next_slice=0382_ae_to_cx_repaired_lineage_client_adapter
```

## Implemented

- Added `ae_repaired_response_runtime_boundary_decision.v1` in
  `services/nex-ae-api/nex_ae_api/repaired_response_boundary.py`.
- Declared canonical owner-service, route-scope, source-contract,
  storage-contract, mutation-policy, and next-slice rules.
- Added redaction guards that allow explicit false raw-content flags while
  rejecting raw content fields, provider details, credentials, database URLs,
  tokens, model paths, and storage paths.
- Added regression coverage for the accepted decision shape, invalid boundary
  shapes, raw-content policy validation, forbidden-field completeness, mutation
  policy, next-slice continuity, and nested sensitive-key detection.

## Evidence

Targeted regression:

```text
./.venv/bin/pytest tests/test_nex_ae_repaired_response_boundary.py -q
21 passed in 0.08s
```

Targeted boundary coverage:

```text
./.venv/bin/pytest tests/test_nex_ae_repaired_response_boundary.py -q --cov=nex_ae_api.repaired_response_boundary --cov-branch --cov-report=term-missing
services/nex-ae-api/nex_ae_api/repaired_response_boundary.py statement_coverage=100% branch_coverage=100%
```

Full quality gate:

```text
scripts/quality/run_quality_gate.sh
2744 passed, 1 warning in 108.00s
statement_coverage=98.64% threshold=95.00%
branch_coverage=96.00% threshold=85.00%
contract_validation=pass schemas=60 examples=92 negative_examples=68 openapi=7
s34_feedback_disposition_closure=pass slice_range=0331-0340 required_files=21
s35_remediation_observability_closure=pass slice_range=0341-0350 required_files=26
s36_remediation_execution_closure=pass slice_range=0351-0360 required_files=33
s37_remediation_runtime_integration_closure=pass slice_range=0361-0370 required_files=31
s38_remediation_operations_automation_closure=pass slice_range=0371-0380 required_files=41
```

Recommended next slices:

```text
Slice 0382: AE-to-CX repaired lineage client adapter
Slice 0383: AE repaired handoff persistence foundation
Slice 0384: AE repaired handoff service API wiring
Slice 0385: AE repaired handoff PostgreSQL smoke evidence
```
