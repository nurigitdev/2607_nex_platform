# Slice 0960: S96 CX Document Intelligence Summary Similarity Closure

## Closure Result

S96 closes as `READY_FOR_S97` with
`CX_DOCUMENT_INTELLIGENCE_SUMMARY_SIMILARITY_READY` readiness.

- Owner-authorized ACTIVE documents use their latest READY extracted Markdown
  as the summary source. Summaries are generated below the 1000-character hard
  limit and persisted through an owner-scoped durable private-text reference.
- Summary generation uses the NeX-MO provider boundary with `Qwen3.5-4B`,
  non-streaming batch semantics, and reasoning disabled so the bounded summary
  remains the visible response payload.
- Summary embeddings use `Qwen3-Embedding-4B` at 2560 dimensions. Public
  metadata, private vector payloads, and `cx_summary_vectors` pgvector lineage
  stay hash-bound and freshness-checked.
- Cosine similarity is permission-first, owner-scoped, limited to current
  READY summaries, and excludes the source document. Results expose only safe
  metadata, hashes, scores, and an owner-authorized bounded preview.
- Ready, similarity, and failure observability is metadata-only and best
  effort. Raw Markdown, summary text, vectors, private storage URIs, provider
  endpoints, and credentials are excluded.

## Actual Evidence

Slice 0959 completed `15/15` protected checks against the actual
`nex_cx_user@nex_cx_test` database and the live DGX generation and embedding
providers. It proved two complete summary lineages, 2560-dimensional pgvector
publication, owner-scoped source-excluding similarity, provider telemetry,
metadata-only events, and complete database/filesystem fixture cleanup.

The active generation endpoint is port `9111` with `Qwen3.5-4B`; the active
embedding profile is `Qwen3-Embedding-4B`. Credentials and private payloads
were not retained in evidence.

## Scope Boundary

This closure claims owner-private document summarization and summary
similarity, not enterprise-wide document intelligence. The following remain
deferred:

- shared/group ACL and cross-owner similarity after canonical OA claims exist;
- summary topic taxonomy, classification, and recommendation workflows;
- multi-tenant similarity scale tuning and production provider SLO baselines.

PostgreSQL/pgvector remains the production vector backend. Versioned SQL plus
the `schema_migrations` runner remains the sole migration history.

## Verification

```bash
./.venv/bin/pytest -q \
  tests/test_s96_cx_document_intelligence_summary_similarity_closure.py \
  --cov=run_s96_cx_document_intelligence_summary_similarity_closure \
  --cov-branch --cov-report=term-missing
./.venv/bin/python \
  scripts/smoke/run_s96_cx_document_intelligence_summary_similarity_closure.py \
  --summary
```

The closure runner is deterministic and performs no database or provider call.
It requires the separately protected Slice 0959 PostgreSQL/DGX evidence before
it can pass.

Observed on 2026-09-23:

- Focused closure suite: `7 passed`.
- Closure runner statement/branch coverage: `100%`/`100%`.
- Closure evidence: `PASS`, deterministic evidence `8/8`, deterministic
  checks `68`, protected PostgreSQL/DGX checks `15`, next requirement `S97`.
- S96 integration suite: `195 passed`.
- Full regression: `7,328 passed`; statement coverage `98.89%`; branch
  coverage `96.59%`.
- Contract validation: `87` JSON Schemas, `138` positive examples, `103`
  negative examples, and `7` OpenAPI documents passed.
- Full quality gate and final S96 closure check completed with exit code `0`.
