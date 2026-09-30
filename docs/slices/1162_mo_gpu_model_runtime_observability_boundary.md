# Slice 1162: MO GPU and model runtime observability boundary

## Goal

Freeze S117 ownership, collection, privacy, caching, persistence, and delivery
boundaries before adding GPU and model runtime diagnostics.

## Result

- S117 owns current GPU and model-process observations for embedding,
  reranking, and generation. S116 remains the owner of durable request and
  retry aggregates.
- Mock collection is deterministic and network-free. Live collection uses an
  explicitly activated, fixed SSH collector and never accepts arbitrary
  commands from API callers.
- Current observations use a short process-local TTL cache. High-frequency GPU
  samples are not stored in PostgreSQL and S117 adds no database table.
- Runtime observations are diagnostic and do not become another service
  readiness dependency.
- SSH targets, provider endpoints and credentials, process IDs and command
  lines, model paths, and GPU UUIDs are forbidden from API and committed
  evidence.
- Requested and loaded dtype remain separate. Loaded dtype is never inferred
  from a model name.

## Planned Slices

1. Slice 1163: runtime observation domain and projection.
2. Slice 1164: protected fixed collector plan.
3. Slice 1165: GPU and model-process normalization.
4. Slice 1166: TTL cache and observation service composition.
5. Slice 1167: authenticated runtime observability API.
6. Slice 1168: thresholds and fail-closed status hardening.
7. Slice 1169: schema, OpenAPI, privacy, and contract hardening.
8. Slice 1170: protected DGX live evidence.
9. Slice 1171: S117 closure and Full Gate.

## Verification

```bash
./.venv/bin/pytest -q \
  tests/test_mo_runtime_observability_boundary.py
./.venv/bin/python \
  scripts/smoke/run_mo_runtime_observability_boundary.py --summary
scripts/quality/run_slice_gate.sh --service nex-mo \
  --test tests/test_mo_runtime_observability_boundary.py \
  --coverage-target \
  services/nex-mo/nex_mo/runtime_observability_boundary.py \
  --smoke scripts/smoke/run_mo_runtime_observability_boundary.py
```

## Quality Evidence

- Focused regression: `4 passed`.
- Slice Gate: `616 passed`, `2` protected PostgreSQL skips.
- Coverage: statement `99.76%`, branch `99.08%`; changed boundary scope
  `100%/100%`.
- Contract validation passed `119` schemas, `177` positive examples, `145`
  negative examples, and `7` OpenAPI documents.
- Boundary evidence passed all eight policy checks across six ownership
  boundaries with zero evidence issues.
