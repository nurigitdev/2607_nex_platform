# Slice 1073: AE Asynchronous Artifact Render Contract

## Goal

Define one strict, owner-bound, content-free contract for durable artifact
render admission and lifecycle projection before persistence and API wiring.

## Changes

- Added `nex_ae_api.async_artifact_rendering` with deterministic render identity,
  request validation, initial render state, and dual queue/render projection.
- Kept execution and domain state explicit: common queue `SUCCEEDED` maps to AE
  render `COMPLETED` and owner-facing lifecycle `READY`.
- Bound every request to tenant, owner, workspace, interaction, CX generation,
  structured draft, source hashes, trace, request, and optional response lineage.
- Excluded structured draft text, generated response content, rendered bytes,
  local storage paths, and secrets from requests and projections.

## Decisions

- A render job ID is deterministic from artifact ID and render request ID, so
  retrying the same admission cannot create duplicate artifact versions.
- Supported transforms remain MD, HTML preview, DOCX, and PDF.
- Render retries are bounded to at most five attempts; the default is three.
- Queue and render state divergence fails closed instead of being presented as
  progress to the owner.

## Verification

```bash
scripts/quality/run_slice_gate.sh --service nex-ae-api \
  --test tests/test_ae_async_artifact_rendering.py \
  --coverage-target services/nex-ae-api/nex_ae_api/async_artifact_rendering.py
```

## Observed Evidence

- Contract tests: `64 passed`; module statement and branch coverage `100%`.
- Slice Gate: `2554 passed`, `4 skipped` protected PostgreSQL tests.
- Coverage: statement `98.03%`, branch `96.02%`.
- Contracts: schemas `103`, examples `161`, negative examples `124`,
  OpenAPI documents `7`.
