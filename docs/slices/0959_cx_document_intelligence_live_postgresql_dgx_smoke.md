# Slice 0959: CX Document Intelligence Live PostgreSQL/DGX Smoke

## Goal

Prove the S96 runtime against the actual CX test database and the live DGX
generation and embedding providers without exposing private payloads or
credentials in evidence.

## Implementation

- Aligns the active generation catalog with the DGX provider moved to port
  `9111`: `qwen3_5_4b_bf16` / `Qwen3.5-4B`. The former 122B NVFP4 profile is
  no longer selected by current runtime defaults.
- Adds a protected, disabled-by-default smoke runner guarded by
  `NEX_CX_DOCUMENT_INTELLIGENCE_LIVE_POSTGRES_SMOKE=1` and a mandatory `test`
  profile.
- Runs current NeX-CX migrations, then verifies `current_database()` and
  `current_user` are exactly `nex_cx_test` and `nex_cx_user` before writing.
- Registers and extracts two documents owned by the same tenant and subject.
- Calls the live MO generation path on port `9111` with `Qwen3.5-4B`, then
  calls the live embedding path with
  `Qwen3-Embedding-4B` for each generated summary.
- Persists summary metadata, private summary text, embedding lineage, and
  2560-dimensional summary vectors; then executes owner-scoped cosine
  similarity while excluding the source document.
- Directly reads PostgreSQL to prove two complete content-summary-embedding-
  vector lineages and checks live-provider telemetry plus metadata-only
  operational events.
- Redacts database credentials and API keys and excludes provider endpoints,
  source text, summary text, vectors, previews, and local storage paths from
  evidence.
- Cleans up both PostgreSQL and temporary filesystem fixtures even when a live
  stage fails.

The quality gate executes the runner in its safe skipped state. A protected
live execution requires explicit runtime environment values and is performed
separately.

The first protected execution exposed and resolved three production-only
boundaries: Qwen thinking output consuming the summary response, float64 to
PostgreSQL float32 vector hash drift, and an untyped nullable UUID bind in the
similarity SQL. These cases now have deterministic regression coverage.

## Verification

```bash
./.venv/bin/pytest -q \
  tests/test_cx_document_intelligence_live_postgres_smoke.py \
  --cov=run_cx_document_intelligence_live_postgres_smoke \
  --cov-branch --cov-report=term-missing
./.venv/bin/python \
  scripts/smoke/run_cx_document_intelligence_live_postgres_smoke.py \
  --summary
```

Observed on 2026-09-23:

- Focused smoke-runner regression: `6 passed`; statement and branch coverage
  both `100%`.
- Full quality gate: `7,321 passed`; statement coverage `98.89%`; branch
  coverage `96.59%`.
- DGX model catalog at port `9111`: `Qwen3.5-4B`.
- Protected live smoke: PASS against database `nex_cx_test` and role
  `nex_cx_user`.
- Two live summaries and two live 2560-dimensional embeddings became READY.
- Owner-scoped similarity returned one candidate while excluding the source.
- Post-cleanup owner content rows: `0`; owner summary-vector rows: `0`.
- Migration `0955_cx_summary_vector_persistence` remained current.
