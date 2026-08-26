# Slice 0351: CX Remediation Execution Boundary Audit and Refactoring Checkpoint

## Scope

Start S36 by freezing the CX-side execution boundary for AG generation
remediation tasks.

This slice does not add a public CX remediation API, database migration, remote
provider call, or AG status callback. It records the ownership and lineage
rules that the next slices must follow before execution contracts and
persistence are added.

## Boundary Decision

- AG remains the owner of remediation task orchestration and operator task
  state.
- CX owns remediation execution and generation lineage once AG asks for a
  model-backed repair.
- MO remains the provider execution boundary; CX still calls MO service APIs,
  not provider endpoints.
- AE API/Web owns the user-visible repaired-result surface and artifact
  rendering.
- CX-executable remediation actions are:
  - `retry_generation`;
  - `retrieval_repair`;
  - `citation_repair`.
- AG-only remediation actions are:
  - `prompt_policy_review`;
  - `operator_followup`;
  - `mark_accepted`.
- CX must not mutate the original generation record. It creates a child repair
  attempt/generation lineage linked by parent/root generation refs.
- CX result refs use `source_service=nex-cx`, `ref_type=repair_execution`, and
  `relation=result_of`.

## Implemented

- Added `cx_remediation_execution_boundary_decision.v1`.
- Added canonical owner-service, action-execution, lineage, handoff, storage,
  and execution-stage policies in
  `services/nex-cx/nex_cx/remediation_execution_boundary.py`.
- Added a raw-safe remediation action intake summary so AG actions can be
  inspected without leaking raw prompts, raw generation output, source text,
  feedback comments, operator notes, evidence text, provider details, tokens,
  credentials, model paths, or storage paths.
- Allowed AG redaction flags such as `raw_prompt_stored=false` while still
  rejecting true raw-content flags and raw-content fields.
- Documented the S36 boundary in the CX service README.

## Refactoring Checkpoint

```text
external_api_changed=false
database_schema_changed=false
remote_provider_required=false
next_slice=0352_cx_remediation_execution_contract_schema_foundation
```

## Evidence

Targeted regression:

```text
./.venv/bin/pytest tests/test_nex_cx_remediation_execution_boundary.py -q
22 passed in 0.04s
```

Full quality gate:

```text
./scripts/quality/run_quality_gate.sh
2431 passed, 1 warning in 78.98s
statement_coverage=98.52% threshold=95.00%
branch_coverage=95.72% threshold=85.00%
contract_validation=pass schemas=57 examples=89 negative_examples=65 openapi=7
s34_feedback_disposition_closure=pass slice_range=0331-0340 required_files=21
s35_remediation_observability_closure=pass slice_range=0341-0350 required_files=26
```

Recommended next slice:

```text
Slice 0352: CX remediation execution contract/schema foundation
```
