# Slice 0404: AE Rendered Artifact Local Storage Adapter

## Scope

Add a private rendered artifact storage boundary for Markdown payloads while
keeping public artifact metadata on logical `ae://artifacts/...` refs.

## Decisions

- `RenderedArtifactStorage` is the narrow payload boundary used by the artifact
  repository. It supports saving and loading rendered Markdown by artifact file
  metadata.
- `InMemoryRenderedArtifactStorage` preserves the current mock/regression path.
- `LocalRenderedArtifactStorage` maps `ae://artifacts/...` refs into a configured
  private root and rejects non-AE schemes, blank segments, and traversal.
- The local root is selected through `NEX_AE_ARTIFACT_STORAGE_ROOT`. This path is
  private implementation state and must not appear in artifact records, API
  responses, smoke evidence, or contracts.

## Evidence

- `./.venv/bin/pytest tests/test_nex_ae_artifacts.py -q --cov=nex_ae_api.artifacts --cov-branch --cov-report=term-missing`
  - `41 passed, 1 warning`
  - `services/nex-ae-api/nex_ae_api/artifacts.py` coverage `96%`
