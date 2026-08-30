# Slice 0449: AG Artifact Collection Operations Projection

## Scope

Add an AG-owned operations projection over the AE artifact collection read-model
so operators can inspect owner-scoped artifact library state without bypassing
the AE API boundary.

## Changes

- Extended `nex_ag.artifact_operations` with
  `ag_artifact_operation_collection_projection.v1`.
- Added `AeArtifactOperationsClient.list_artifacts(...)` to both the in-memory
  and HTTP AE artifact clients.
- Added `GET /admin/v1/operations/artifacts` with required tenant, workspace,
  and owner scope, optional status, and bounded limit validation.
- Added collection summaries for ready/draft/failed counts, downloadable and
  previewable item counts, status counts, and latest update time.
- Added regression coverage for projection redaction, owner-scope filtering,
  route validation, HTTP client query parameters, source failures, and main app
  route registration.

## Decisions

- AE remains the system of record for artifact collection data.
- AG reads the AE collection through the same client boundary used for artifact
  detail projections.
- The AG projection is metadata-only. It keeps ids, statuses, safe artifact
  routes, counts, target formats, quality summaries, and source hashes, but
  excludes rendered content, download payloads, local storage paths, provider
  endpoints, database URLs, and credentials.
- Collection queries must always be owner-scoped before they can appear in AG
  operations surfaces.

## Evidence

Targeted regression:

```bash
./.venv/bin/pytest tests/test_nex_ag_artifact_operations.py -q --cov=nex_ag.artifact_operations --cov=nex_ag.main --cov-branch --cov-report=term-missing
```

Full quality gate:

```bash
./scripts/quality/run_quality_gate.sh
```
