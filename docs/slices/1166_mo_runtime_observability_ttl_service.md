# Slice 1166: MO runtime observability TTL service

## Goal

Compose planning, collection, caching, invalidation, and safe failure projection
into a bounded runtime observation service.

## Result

- Added a process-local single-flight TTL store with `MISS`, `FRESH`,
  `REFRESHED`, and `STALE` semantics.
- Reused a fresh snapshot, refreshed expired or forced observations, and
  retained the previous snapshot as explicitly `STALE/UNKNOWN` when refresh
  failed.
- Added a 30-second default TTL with a validated 1-300 second operator range.
- Invalidated cached observations whenever private target, port, model, dtype,
  timeout, or collector configuration changed.
- Returned a stable privacy-safe `UNKNOWN` projection for initial planning,
  clock, collection, and configuration failures.
- Kept S117 state process-local with no database migration or PostgreSQL smoke.

## Verification

```bash
./.venv/bin/pytest -q \
  tests/test_mo_runtime_observability_cache.py \
  tests/test_mo_runtime_observability_service.py
./.venv/bin/python \
  scripts/smoke/run_mo_runtime_observability_service.py --summary
scripts/quality/run_checkpoint_gate.sh \
  --test tests/test_mo_runtime_observability_cache.py \
  --test tests/test_mo_runtime_observability_service.py \
  --coverage-target services/nex-mo/nex_mo/runtime_observability_cache.py \
  --coverage-target services/nex-mo/nex_mo/runtime_observability_service.py \
  --smoke scripts/smoke/run_mo_runtime_observability_service.py
```

## Quality Evidence

- Focused cache/service regression: `22 passed`; all three changed scopes
  statement/branch `100%/100%`.
- Fifth-Slice Checkpoint Gate: `8,854 passed`, `7` protected smoke skips, and
  `123` warnings in `538.97s`.
- Repository coverage remained above policy at statement `98.76%` and branch
  `96.94%`; both changed cache/service scopes remained `100%/100%`.
- Contract validation passed `119` schemas, `177` positive examples, `145`
  negative examples, and `7` OpenAPI documents.
- Deterministic service evidence passed all five checks with `3/3` healthy
  models, a 30-second TTL, and no persistent table.
