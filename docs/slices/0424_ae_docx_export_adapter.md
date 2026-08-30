# Slice 0424: AE DOCX Export Adapter

## Scope

Add DOCX export materialization behind the AE artifact render route while
keeping PDF and richer asynchronous export orchestration deferred.

## Changes

- Enabled `DOCX` in `ARTIFACT_TRANSFORMER_CATALOG`.
- Added `render_docx_export_from_markdown(...)` using the existing
  `python-docx` dependency.
- Added `build_docx_export_artifact_file(...)` so the DOCX path has the same
  deterministic file metadata and payload hash behavior as Markdown and HTML.
- Extended Markdown-derived render payload creation to produce DOCX bytes when
  requested by the artifact handoff.
- Updated download responses so text formats continue returning `content`,
  while binary formats return `content_base64` with
  `content_encoding=base64`.
- Kept binary preview blocked with `ae.artifact_file_preview_unavailable`.

## Decisions

- DOCX export remains AE-owned. CX still supplies the validated structured
  draft, and AE transforms the safe Markdown rendering into export bytes.
- DOCX generation is synchronous for now because the current render route is
  still synchronous. S43 should revisit explicit multi-stage job progress when
  PDF and larger exports are added.
- Binary download uses base64 JSON in this slice to preserve the existing route
  shape. A later browser/export slice can introduce streamed file responses or
  signed object-storage URLs without changing artifact metadata lineage.
- `PDF` remains cataloged but unimplemented.

## Evidence

Targeted regression:

```bash
./.venv/bin/pytest tests/test_nex_ae_artifacts.py tests/test_ae_artifact_export_transform_boundary_audit.py -q --cov=nex_ae_api.artifacts --cov=run_ae_artifact_export_transform_boundary_audit --cov-branch --cov-report=term-missing
```

Expected S43 audit movement:

```bash
./.venv/bin/python scripts/smoke/run_ae_artifact_export_transform_boundary_audit.py --summary
ae_artifact_export_transform_boundary_audit=pass ... gaps_ready=4/8 next=Slice 0425
```

Full quality gate:

```bash
./scripts/quality/run_quality_gate.sh
```

No PostgreSQL smoke is required for this slice because the artifact metadata
schema is unchanged. DOCX bytes remain outside the database behind private
rendered artifact storage and logical `ae://artifacts/...` refs.
