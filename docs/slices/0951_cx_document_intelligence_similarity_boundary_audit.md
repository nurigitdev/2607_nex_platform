# Slice 0951: CX Document Intelligence and Summary Similarity Boundary Audit

## Goal

Freeze the S96 private summary generation, storage, embedding, freshness,
similarity, API, and observability boundaries before extending the CX runtime.

## Findings

- CX already enforces owner authorization on summary and summary-embedding
  routes and keeps cross-owner resources indistinguishable from missing ones.
- Summary output is limited to 1000 characters, uses the prompt registry, and
  has public metadata persistence in `cx_document_summaries`.
- Summary embedding metadata persists in
  `cx_document_summary_embeddings`, and durable ingestion already includes
  summary and summary-embedding steps.
- Current summary generation is a deterministic local mock over normalized
  Markdown rather than the configured generation provider.
- Private summary text uses a `memory://` URI and process-local dictionary;
  summary embedding vectors are also process-local.
- The current schema stores summary embedding metadata but no pgvector payload,
  freshness manifest, owner-scoped similarity query, or similarity API.
- There is no document-intelligence-specific metadata-only operational event
  boundary.

## Decision

- S96 operates only on private ACTIVE documents visible to the authenticated
  tenant and owner subject.
- The source is the latest READY extracted Markdown. Generated summaries remain
  below the existing 1000-character hard limit and are stored as private
  durable payloads referenced by public metadata.
- The current generation profile is `Qwen3.5-122B-A10B-NVFP4`; summary vectors
  use `Qwen3-Embedding-4B`, dimension 2560, and cosine similarity.
- PostgreSQL/pgvector is the production summary-vector backend, with owner and
  freshness filtering before similarity ranking.
- Similarity results may expose document metadata, hashes, scores, and a bounded
  owner-authorized preview, but never raw vectors or cross-owner identities.
- Slices 0951-0958 remain deterministic/mock-first. Slice 0959 requires the
  actual `nex_cx_test` database plus live generation and embedding providers.
- Shared/group ACL similarity, topic taxonomy/classification, and scale tuning
  remain deferred.

This Slice adds no table, migration, route, provider call, or persistent row.

## Slice Plan

1. Slice 0951: boundary audit and refactoring checkpoint.
2. Slice 0952: document intelligence summary/freshness contract.
3. Slice 0953: durable private summary text storage.
4. Slice 0954: generation-provider summary adapter.
5. Slice 0955: summary-vector pgvector persistence and freshness.
6. Slice 0956: owner-scoped summary similarity adapter.
7. Slice 0957: document intelligence orchestration and API wiring.
8. Slice 0958: operations observability and contract hardening.
9. Slice 0959: actual PostgreSQL plus live generation/embedding smoke.
10. Slice 0960: S96 closure.

## Verification

```bash
./.venv/bin/pytest -q \
  tests/test_cx_document_intelligence_similarity_boundary_audit.py \
  --cov=run_cx_document_intelligence_similarity_boundary_audit \
  --cov-branch --cov-report=term-missing
./.venv/bin/python \
  scripts/smoke/run_cx_document_intelligence_similarity_boundary_audit.py \
  --summary
```

PostgreSQL and DGX providers are intentionally not invoked in this audit Slice.

Observed on 2026-09-22:

- Focused audit suite: `5 passed`.
- Audit runner statement/branch coverage: 100%/100%.
- Boundary evidence: `PASS`, foundations `8`, confirmed gaps `7`, issues `0`,
  remote providers required now `False`.
- Full regression: `7149 passed`, statement coverage `98.88%`, branch coverage
  `96.56%`.
- Contract validation: 85 JSON Schemas, 136 examples, 101 negative examples,
  and 7 OpenAPI documents passed.
- Full quality gate completed with exit code `0`.
