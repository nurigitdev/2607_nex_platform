# Slice 0467: AE artifact retention store purge capability

## Scope

Add the guarded artifact retention purge capability to the AE artifact stores
before exposing a service API route.

## Changes

- Added `purge_retention_candidates(...)` to the in-memory and SQLAlchemy AE
  artifact record stores.
- Added rendered artifact storage deletion support for in-memory and local
  filesystem-backed adapters.
- Kept dry-run as the default purge mode and returned
  `ae_artifact_retention_execution.v1` evidence for dry-run, blocked execute,
  and guarded execute paths.
- Added guarded physical deletion of artifact graph rows in child-first order:
  links, files, render jobs, versions, source refs, and artifact rows.
- Left artifact handoff records intact so source request lineage remains
  auditable after artifact purge.
- Added regression coverage for dry-run safety, missing-delete-flag blocking,
  guarded deletion, scan limits, local storage deletion, SQLite SQLAlchemy row
  deletion, and SQLAlchemy error mapping.

## Decisions

- Store purge remains unavailable through HTTP until the next API guardrail
  slice.
- Successful execute requires all three flags:
  `delete_enabled`, `storage_mutation_enabled`, and
  `database_row_delete_enabled`.
- Purge execution evidence remains metadata-only and must not include
  `storage_ref`, rendered payloads, filesystem paths, provider secrets, or
  database URLs.
- Batch deletion is bounded by `max_delete_count`, with a default of 20 and
  hard maximum of 100.

## Evidence

```bash
./.venv/bin/pytest tests/test_nex_ae_artifacts.py -q --cov=nex_ae_api.artifacts --cov-branch --cov-report=term-missing
```
