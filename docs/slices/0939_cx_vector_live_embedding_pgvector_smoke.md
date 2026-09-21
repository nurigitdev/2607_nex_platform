# Slice 0939: CX Remote Embedding to pgvector Live Smoke

## Goal

Prove the S94 production-shaped path once against both the OpenAI-compatible
DGX embedding provider and the actual `nex_cx_test` pgvector database.

## Protected Boundary

- The smoke is disabled unless
  `NEX_CX_VECTOR_LIVE_EMBEDDING_PGVECTOR_SMOKE=1`.
- Only the `test` profile, `nex_cx_user` role, and `nex_cx_test` database are
  accepted.
- The remote provider must use `openai_embeddings`, an explicit API key, and a
  model included in `NEX_MO_LIVE_EXPECTED_EMBEDDING_MODELS`.
- The returned vector must contain exactly 2560 finite values and must not be
  an all-zero vector.

## End-to-End Evidence

The protected smoke requests one Korean embedding, builds a provider-matched
embedding profile, atomically publishes the returned vector to pgvector, and
queries the READY index through the Slice 0937 freshness guard. It verifies
the persisted provider lineage, vector dimension, payload count, fresh
retrieval admission, matching chunk, and self-similarity before deleting all
fixture rows.

Evidence contains only safe configuration metadata and aggregate checks. The
provider URL, API key, source text, and vector values are excluded.

## Commands

```bash
./.venv/bin/pytest -q tests/test_cx_vector_live_embedding_pgvector_smoke.py

NEX_CX_VECTOR_LIVE_EMBEDDING_PGVECTOR_SMOKE=1 \
NEX_CX_TEST_DATABASE_URL='postgresql://.../nex_cx_test' \
NEX_MO_REMOTE_EMBEDDING_URL='http://.../v1/embeddings' \
NEX_MO_REMOTE_EMBEDDING_API_KEY='<api-key>' \
NEX_MO_REMOTE_EMBEDDING_MODEL='Qwen3-Embedding-4B' \
NEX_MO_LIVE_EXPECTED_EMBEDDING_MODELS='Qwen3-Embedding-4B' \
./.venv/bin/python \
  scripts/smoke/run_cx_vector_live_embedding_pgvector_smoke.py --summary
```

## Observed Evidence

Observed on 2026-09-22:

- Fake-provider focused regression: `9 passed`.
- The protected smoke runner's included code is covered at statement/branch
  `100%/100%`; the actual network and PostgreSQL execution body is explicitly
  protected from ordinary regression coverage.
- Protected live smoke: `11/11` checks passed against the actual DGX
  OpenAI-compatible embedding provider and `nex_cx_test`.
- The provider returned one 2560-dimensional, finite, non-zero vector.
- Atomic publish persisted the provider profile and READY payload checkpoint;
  freshness-gated pgvector retrieval returned the source chunk with self-
  similarity within `1e-6` of `1.0`.
- Independent fixture audit after execution: `cx_vector_indexes=0`,
  `cx_vectors=0`, and `cx_content_objects=0` for the Slice tenant.
- Full quality gate: `6831 passed`; statement coverage `98.86%`, branch
  coverage `96.47%`, and contract validation passed (`85` schemas, `136`
  examples, `101` negative examples, `7` OpenAPI documents).
