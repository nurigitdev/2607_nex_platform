# Slice 0442: AE Artifact Collection Read-Model Foundation

## Scope

Add the service-side artifact collection read-model before exposing a public list
route.

## Changes

- Added `ae_artifact_collection.v1` and `ae_artifact_collection_item.v1` runtime
  schema constants.
- Added owner-scoped `list_artifacts` support to both in-memory and SQLAlchemy
  artifact stores.
- Added collection filter validation for tenant, workspace, owner, status, and
  bounded limit.
- Added metadata-only collection item builders that summarize versions, files,
  links, render job state, source lineage, and quality metadata without rendered
  payloads or storage paths.
- Extended artifact regression tests with in-memory, SQLite, validation, and DB
  error mapping coverage.

## Decisions

- The collection read-model remains AE-owned and route-free in this slice.
- Collection scope is explicitly tenant/workspace/owner.
- Collection items include route metadata for detail and version lookup, but do
  not include file/link arrays, rendered content, base64 payloads, storage refs,
  local storage roots, database URLs, or provider secrets.
- Pagination is intentionally bounded by `limit` only for the first foundation;
  cursor support can be added after the browser library surface proves the
  access pattern.

## Evidence

Targeted regression:

```bash
./.venv/bin/pytest tests/test_nex_ae_artifacts.py -q --cov=nex_ae_api.artifacts --cov-branch --cov-report=term-missing
```

Full quality gate:

```bash
./scripts/quality/run_quality_gate.sh
```
