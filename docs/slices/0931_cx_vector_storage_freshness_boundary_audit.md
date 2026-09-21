# Slice 0931: CX vector storage and index freshness boundary audit

## Goal

Freeze the S94 vector-payload, metadata, freshness, and provider boundary before
changing runtime storage or schema.

## Findings

- S92 already provides the owner-scoped `CxVectorStore` capability and a
  restart-safe filesystem reference adapter.
- `cx_chunk_embeddings` and `cx_document_summary_embeddings` already persist
  provider/model lineage, dimension, hash, storage URI, and a coarse status.
- The embedding runtime still writes vectors to process-local dictionaries and
  does not use the private vector capability.
- `NEX_CX_VECTOR_DATABASE_URL` reserves a future split database, but no
  PostgreSQL/pgvector adapter currently consumes it.
- Retrieval treats any present embedding index as `READY`; it does not compare
  chunk, model, profile, dimension, or payload fingerprints.
- There is no protected index-readiness/rebuild surface or end-to-end evidence
  combining PostgreSQL metadata, pgvector payloads, and the live embedding
  provider.

## Decision

- PostgreSQL remains the metadata system of record. The short
  `cx_vector_indexes` manifest will own profile and freshness state.
- Vector payloads use the existing `CxVectorStore` port. The production adapter
  will use the short `cx_vectors` pgvector table and route through
  `NEX_CX_VECTOR_DATABASE_URL`, falling back to the primary CX database when
  the override is empty.
- The filesystem adapter remains the deterministic local-regression fallback.
- Only owner-scoped, `READY`, fingerprint-compatible indexes may participate in
  retrieval.
- The live Qwen3-Embedding-4B provider is not required for Slices 0931-0938.
  It is required once in protected Slice 0939 evidence together with the actual
  `nex_cx_test` database and expected dimension `2560`.

This Slice adds no table, migration, route, provider call, or persistent row.

## Slice plan

1. Slice 0931: boundary audit.
2. Slice 0932: embedding profile and freshness contract.
3. Slice 0933: vector manifest and payload persistence schema.
4. Slice 0934: owner-scoped pgvector adapter and optional DB routing.
5. Slice 0935: atomic private-vector publish wiring.
6. Slice 0936: stale detection, reindex planning, and reconciliation.
7. Slice 0937: retrieval freshness enforcement.
8. Slice 0938: protected readiness API and observability.
9. Slice 0939: actual PostgreSQL and remote embedding live smoke.
10. Slice 0940: S94 closure.

## Verification

```bash
./.venv/bin/pytest -q \
  tests/test_cx_vector_storage_freshness_boundary_audit.py
./.venv/bin/python \
  scripts/smoke/run_cx_vector_storage_freshness_boundary_audit.py --summary
```

Observed on 2026-09-21:

- Focused audit suite: `5 passed`; audit runner statement coverage `100%`.
- Boundary evidence: `PASS`, foundations `6`, gaps `6`, remote provider
  required now `False`.
- Full quality gate: `6681 passed`; statement coverage `98.84%`; branch
  coverage `96.42%`.
- Contract validation: `85 schemas`, `136 positive examples`, `101 negative
  examples`, and `7 OpenAPI documents` passed.
- PostgreSQL, pgvector, and DGX Spark were not invoked in this audit Slice.
