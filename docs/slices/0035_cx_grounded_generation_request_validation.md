# Slice 0035 CX Grounded Generation Request Validation

Status: Implemented.

Backlog candidate: `S4-005` CX grounded generation request validation.

Requirement coverage: `CX-FR-007`, `AEAPI-FR-003`, `TRACE-GEN-001`.

## Scope

Slice 0035 connects generation compatibility rules to the CX generation facade:

- Retrieval-free mock generation is explicitly treated as `GENERAL_ANSWER`.
- AE grounded chat sends `GROUNDED_ANSWER`, `grounded-answer`, and a
  `retrieval_package_ref`.
- CX selects an active compatibility rule before MO execution.
- Grounded generation requires an existing `READY` retrieval package with a
  matching package hash.
- `selected_evidence_ids` must be a subset of the referenced retrieval package.
- CX generation execution records expose compatibility and retrieval lineage
  metadata without copying source text.

## Files

- `services/nex-cx/nex_cx/generation.py`
- `services/nex-ae-api/nex_ae_api/chat.py`
- `scripts/smoke/run_traceable_mock_flow.py`
- `contracts/schemas/generation/cx_generation_execution_record.v1.schema.json`
- `tests/test_nex_cx_generation.py`

## Evidence

Slice evidence should include:

```bash
scripts/quality/run_quality_gate.sh
```

Regression tests cover general-answer compatibility, grounded happy path,
missing retrieval refs, missing retrieval state, hash mismatch, not-ready
retrieval packages, selected evidence mismatch, and traceable mock smoke flow.
