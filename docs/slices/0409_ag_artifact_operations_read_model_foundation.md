# Slice 0409: AG Artifact Operations Read-Model Foundation

## Scope

Add an AG-owned artifact operations detail read-model over AE artifact runtime
metadata so operators can inspect artifact lineage, render status, file/link
metadata, and chat attachment references without exposing generated content or
local storage paths.

## Decisions

- AE remains the artifact system of record; AG reads through an AE source
  client instead of directly writing AE tables.
- The first route is a detail projection:
  `GET /admin/v1/operations/artifacts/{artifact_id}`.
- Optional handoff and chat-link lookups degrade the projection instead of
  hiding the primary artifact record when the primary artifact read succeeded.
- AG projection keeps IDs, hashes, statuses, route names, quality summaries, and
  logical `ae://artifacts/...` storage refs, but removes markdown content, raw
  source text, prompts, local filesystem paths, and unsafe routes.
- `nex-ag/main.py` registers the route by default with an HTTP AE client using
  `NEX_AG_AE_ARTIFACT_BASE_URL`, `NEX_AG_AE_ARTIFACT_SERVICE_TOKEN`, and
  `NEX_AG_AE_ARTIFACT_TIMEOUT_SECONDS` when provided.

## Evidence

- `./.venv/bin/pytest tests/test_nex_ag_artifact_operations.py -q --cov=nex_ag.artifact_operations --cov=nex_ag.main --cov-branch --cov-report=term-missing`
  - `14 passed, 1 warning`
  - `services/nex-ag/nex_ag/artifact_operations.py` coverage `100%`
- `scripts/quality/run_quality_gate.sh`
  - `2966 passed, 1 warning`
  - `statement_coverage=98.71% threshold=95.00%`
  - `branch_coverage=96.21% threshold=85.00%`
