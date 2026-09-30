# Slice 1126: MO provider readiness TTL cache

## Goal

Add the bounded process-local cache required by the S113 readiness boundary,
including single-flight refresh and fail-closed stale behavior.

## Result

- The store distinguishes `MISS`, `FRESH`, and `STALE` lookups.
- Fresh reads reuse the cached provider snapshot without repeating probes.
- Expiry and explicit force-refresh produce a `REFRESHED` snapshot.
- Concurrent cache misses are serialized into one refresh operation.
- A refresh failure with prior evidence returns `STALE/NOT_READY` without
  exposing exception details; an initial refresh failure remains visible to
  the caller for safe composition in Slice 1127.
- The cache remains process-local and introduces no S113 database table.

Slice Gate passed with 360 tests, statement coverage 99.66%, and branch
coverage 98.69%. Both changed executable scopes have 100% statement and branch
coverage.

The fifth-Slice Checkpoint Gate passed with 8,527 tests and 5 protected-smoke
skips. Checkpoint statement coverage was 98.73% and branch coverage was 96.88%.
Contract validation passed with 109 schemas, 167 examples, 132 negative
examples, and 7 OpenAPI documents.

## Verification

```bash
./.venv/bin/pytest -q tests/test_mo_provider_readiness_cache.py \
  --cov=nex_mo.provider_readiness_cache \
  --cov=run_mo_provider_readiness_cache \
  --cov-branch --cov-report=term-missing

./.venv/bin/python \
  scripts/smoke/run_mo_provider_readiness_cache.py --summary
```
