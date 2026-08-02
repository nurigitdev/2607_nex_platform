# Slice 0038 AE Artifact Handoff Metadata

Status: Implemented.

Backlog candidate: `S4-008` AE artifact handoff metadata from validated CX draft
lineage.

Requirement coverage: `AEAPI-FR-004`, `AEAPI-FR-005`, `CX-FR-008`,
`AG-FR-003`, `TRACE-GEN-001`.

## Scope

Slice 0038 adds the first AE-owned artifact handoff boundary:

- `ae_artifact_handoff.v1` JSON Schema with safe lineage, rendering intent,
  target format, validation, actor, workspace, and retention metadata.
- Positive and negative contract fixtures for artifact handoff records.
- AE artifact handoff routes:
  `/api/v1/artifact-handoffs` and
  `/api/v1/artifact-handoffs/{artifact_handoff_id}`.
- HTTP client methods for AE to read CX generation records and structured
  drafts before handoff creation.
- Guardrails that reject non-completed CX generations, unvalidated structured
  drafts, citation validation failures, source draft mismatches, and unsupported
  render formats.

This slice intentionally stops before rendering files. The handoff package is
the safe pre-render record that later artifact version, render job, preview,
download, and chat artifact link slices can consume.

## Files

- `services/nex-ae-api/nex_ae_api/artifacts.py`
- `services/nex-ae-api/nex_ae_api/main.py`
- `contracts/schemas/generation/ae_artifact_handoff.v1.schema.json`
- `tests/test_nex_ae_artifacts.py`

## Evidence

Slice evidence should include:

```bash
scripts/quality/run_quality_gate.sh
```

Regression tests cover handoff record construction, safe hash-only lineage,
target format normalization, route create/readback, authentication, missing
record handling, invalid payload mapping, CX HTTP error mapping, source
generation readiness, citation validation, and source draft mismatch guards.
