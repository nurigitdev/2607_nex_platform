# Slice 0421: AE Artifact Export/Transform Boundary Audit

## Scope

Start S43 by freezing the AE artifact export/transform boundary before adding
real multi-format materializers.

## Findings

- AE API is still the artifact transform owner. CX owns source generation and
  structured drafts, AE Web owns request/display surfaces, and AG observes
  operations through redacted read models.
- Contracts already allow `MD`, `HTML_PREVIEW`, `DOCX`, and `PDF` target
  formats.
- AE Web already exposes a format selector and mock artifact metadata for
  future export formats.
- The actual AE render route remains intentionally Markdown-only:
  non-`MD` render requests are rejected by the current guard, and the current
  render response schema is `ae_markdown_render_result.v1`.
- Rendered payload storage is isolated behind the artifact storage adapter, but
  the adapter methods are still Markdown-specific.

## Decisions

- S43 export/transform work should stay inside `nex-ae-api`; it should not move
  format conversion to CX or the browser.
- `HTML_PREVIEW`, `DOCX`, and `PDF` should be added behind the existing render
  job, artifact version, artifact file, link, and private payload storage
  boundary.
- The storage adapter should become format-neutral before several export
  materializers are added.
- PostgreSQL smoke evidence is not required for this audit slice. It should be
  added once multi-format files are persisted and must use the protected
  `nex_ae_test` profile.

## Next Slices

- Slice 0422: AE export/transform catalog and format-neutral storage contract.
- Slice 0423: AE HTML preview materializer.
- Slice 0424: AE DOCX export adapter.
- Slice 0425: AE PDF export adapter.
- Slice 0426: AE artifact export PostgreSQL smoke evidence and AE Web request
  wiring checkpoint.

## Evidence

```bash
./.venv/bin/python scripts/smoke/run_ae_artifact_export_transform_boundary_audit.py --summary
ae_artifact_export_transform_boundary_audit=pass paths=18/18 token_groups=6/6 gaps_ready=0/8 next=Slice_0422
```

```bash
./.venv/bin/pytest tests/test_ae_artifact_export_transform_boundary_audit.py -q --cov=run_ae_artifact_export_transform_boundary_audit --cov-branch --cov-report=term-missing
run_ae_artifact_export_transform_boundary_audit.py statement_coverage=100% branch_coverage=100%
```

The audit is static and local-only. Evidence must not include database URLs,
service tokens, provider API keys, raw prompts, raw generation output, raw source
document text, raw download content, local storage paths, or physical storage
refs.
