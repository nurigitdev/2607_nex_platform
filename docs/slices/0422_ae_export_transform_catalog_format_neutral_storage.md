# Slice 0422: AE Export/Transform Catalog and Format-Neutral Storage

## Scope

Add the first S43 runtime foundation for multi-format artifact export without
changing the existing Markdown render route behavior.

## Changes

- Added `ARTIFACT_TRANSFORMER_CATALOG` in `nex_ae_api.artifacts`.
- Centralized target format metadata for `MD`, `HTML_PREVIEW`, `DOCX`, and
  `PDF`: MIME type, extension, render stage, content kind, materializer id, and
  implementation flag.
- Added format helpers for MIME type, extension, content kind, and deterministic
  artifact file names.
- Added a format-neutral artifact file metadata builder that hashes payload
  bytes and still emits only logical `ae://artifacts/...` storage refs.
- Added bytes-based rendered payload storage methods:
  `save_rendered_artifact_file(...)` and
  `get_rendered_artifact_file(...)`.
- Kept `save_markdown(...)` and `get_markdown(...)` as compatibility wrappers
  so the current Markdown route and existing public API shape remain stable.

## Decisions

- `MD` remains the only implemented materializer in this slice.
- `HTML_PREVIEW`, `DOCX`, and `PDF` are explicit catalog entries but remain
  disabled for runtime materialization until later S43 slices.
- The private storage adapter now treats rendered artifacts as bytes. Text
  formats decode at the route boundary; binary formats can be downloaded later
  without forcing raw bytes into JSON or browser surfaces.
- No PostgreSQL smoke is required for this slice because the DB metadata shape
  is unchanged. The existing artifact PostgreSQL smoke remains the protected
  persistence evidence path.

## Evidence

```bash
./.venv/bin/pytest tests/test_nex_ae_artifacts.py -q --cov=nex_ae_api.artifacts --cov-branch --cov-report=term-missing
```

```bash
./scripts/quality/run_quality_gate.sh
```

Expected S43 audit movement after this slice:

```bash
./.venv/bin/python scripts/smoke/run_ae_artifact_export_transform_boundary_audit.py --summary
ae_artifact_export_transform_boundary_audit=pass ... next=Slice_0422
```

The storage contract must not expose database URLs, service tokens, provider API
keys, raw prompts, raw generation output, raw source document text, raw download
content, local storage paths, or physical storage refs.
