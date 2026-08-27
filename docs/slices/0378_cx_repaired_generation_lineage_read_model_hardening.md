# Slice 0378: CX Repaired Generation Lineage Read-Model Hardening

## Scope

Harden the CX remediation execution detail projection with an explicit repaired
generation lineage block. The detail response now exposes the parent, root,
remediation action, optional repaired generation, result ref, diagnostics, safe
debug paths, and redaction guarantees without requiring AG or AE consumers to
re-derive lineage from the embedded execution row.

## Changes

- Added `cx_repaired_generation_lineage.v1` to
  `cx_remediation_execution_detail.v1`.
- Classified runtime lineage as:
  - `PENDING_REPAIR_GENERATION` for accepted/running attempts without a child;
  - `LINKED` when a distinct repaired generation id is present;
  - `TERMINAL_WITHOUT_REPAIR` for failed/cancelled attempts without a child;
  - `INCONSISTENT` for succeeded attempts without a child or self-linked
    repair generation ids.
- Added closed OpenAPI schema coverage for the new lineage projection.
- Extended the CX read-model PostgreSQL smoke runner to assert lineage schema,
  pending status, parent-independent reads, and redaction safety.

## Evidence

- Regression tests cover pending, linked, terminal, inconsistent, and unsafe
  result-ref sanitization paths.
- PostgreSQL smoke evidence remains guarded by
  `NEX_CX_REMEDIATION_EXECUTION_READ_MODEL_POSTGRES_SMOKE=1` and writes only to
  the CX test database.

## Next

This read-model can be consumed by AG operations and AE repaired-result views
without expanding the CX execution row contract or exposing raw prompt/output
content.
