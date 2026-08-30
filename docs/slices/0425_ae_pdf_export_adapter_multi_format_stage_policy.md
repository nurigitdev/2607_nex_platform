# Slice 0425: AE PDF Export Adapter and Multi-Format Stage Policy

## Scope

Complete the first synchronous AE-owned export set by adding PDF materialization
and freezing a canonical multi-format render stage order.

## Changes

- Enabled `PDF` in `ARTIFACT_TRANSFORMER_CATALOG`.
- Added `MULTI_FORMAT_RENDER_STAGE_ORDER` and
  `render_stage_sequence_for_formats(...)`.
- Included the canonical render stage sequence in the render policy hash so
  rerender identity changes when the requested format set changes.
- Added `render_pdf_export_from_markdown(...)` with a deterministic text PDF
  writer that does not require a new runtime dependency.
- Added `build_pdf_export_artifact_file(...)` so PDF metadata follows the same
  logical storage refs, payload hash, file name, and link behavior as MD, HTML,
  and DOCX.
- Extended binary download support to include PDF base64 payloads through the
  existing download JSON boundary.

## Decisions

- PDF export remains AE-owned and is derived from AE's validated Markdown
  rendering of the CX structured draft.
- This slice intentionally implements a simple text PDF. Rich layout, embedded
  Korean fonts, and brand styling should be handled in a later export quality
  slice.
- Preview remains text-only. DOCX/PDF preview requests return
  `ae.artifact_file_preview_unavailable`.
- PostgreSQL schema remains unchanged; rendered bytes still live outside the
  database behind private rendered artifact storage.

## Evidence

Targeted regression:

```bash
./.venv/bin/pytest tests/test_nex_ae_artifacts.py tests/test_ae_artifact_export_transform_boundary_audit.py -q --cov=nex_ae_api.artifacts --cov=run_ae_artifact_export_transform_boundary_audit --cov-branch --cov-report=term-missing
```

Expected S43 audit movement:

```bash
./.venv/bin/python scripts/smoke/run_ae_artifact_export_transform_boundary_audit.py --summary
ae_artifact_export_transform_boundary_audit=pass ... gaps_ready=6/8 next=Slice 0426
```

Full quality gate:

```bash
./scripts/quality/run_quality_gate.sh
```
