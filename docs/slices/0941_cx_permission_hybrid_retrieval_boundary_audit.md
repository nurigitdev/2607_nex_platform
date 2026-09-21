# Slice 0941: CX Permission-Filtered Hybrid Retrieval Boundary Audit

## Goal

Freeze the S95 authorization, lexical, vector, fusion, reranking, and evidence
boundaries before changing the retrieval runtime.

## Findings

- S92 provides trusted service-to-service access context and exact tenant/owner
  visibility checks for private ACTIVE content.
- S94 provides owner-scoped pgvector payloads and admits only READY,
  source/profile/payload-compatible vector indexes.
- The current retrieval path filters the requested document IDs by owner before
  ranking and returns not-found for explicitly requested cross-owner content.
- Weighted RRF already defines vector `0.7`, BM25 `0.3`, and `k=60`; MeCab-ko
  query tokenization follows the index tokenizer with `korean_mixed_v1`
  fallback.
- Candidate generation still reads process-local chunk, lexical, and embedding
  dictionaries. Its lexical score is term coverage rather than BM25, and it
  does not consume the fresh pgvector retrieval guard.
- Evidence permission results and filtered counts are fixed mock values, so the
  persisted permission snapshot does not yet prove the actual decision path.
- Reranking occurs after the current document filter, but permission continuity
  across candidate generation, reranker input, and evidence output is not an
  explicit runtime invariant.

## Decision

- The S95 MVP permission model is private tenant plus owner-subject exact match;
  only ACTIVE content is eligible.
- Cross-owner and inactive resources are removed before candidate generation
  and remain indistinguishable from missing resources.
- Processing order is authentication, subject resolution, owner filtering,
  freshness admission, BM25/vector ranking, then reranking of authorized text.
- Permission snapshots record measured requested, visible, filtered-document,
  and filtered-chunk counts and are hash-bound to the retrieval package.
- Shared documents, groups, and ACL expansion remain deferred until OA exposes
  a canonical permission-claim contract.
- PostgreSQL/pgvector is the production retrieval backend. Deterministic local
  regression may continue using in-memory adapters.
- Remote embedding and reranker providers are not needed for Slices 0941-0948;
  Slice 0949 will require both providers and actual `nex_cx_test`.

This Slice adds no table, migration, route, provider call, or persistent row.

## Slice Plan

1. Slice 0941: boundary audit.
2. Slice 0942: permission decision and snapshot contract.
3. Slice 0943: owner-scoped lexical candidate adapter.
4. Slice 0944: fresh vector candidate adapter.
5. Slice 0945: permission-first hybrid orchestration.
6. Slice 0946: weighted RRF and rerank privacy hardening.
7. Slice 0947: retrieval package API and persistence wiring.
8. Slice 0948: retrieval operations observability.
9. Slice 0949: actual PostgreSQL plus remote embedding/reranker smoke.
10. Slice 0950: S95 closure.

## Verification

```bash
./.venv/bin/pytest -q \
  tests/test_cx_permission_hybrid_retrieval_boundary_audit.py
./.venv/bin/python \
  scripts/smoke/run_cx_permission_hybrid_retrieval_boundary_audit.py --summary
```

Observed on 2026-09-22:

- Focused audit suite: `5 passed`; audit runner statement and branch coverage
  `100%`.
- Boundary evidence: `PASS`, foundations `7`, gaps `7`, issues `0`, remote
  providers required now `False`.
- Full quality gate: `6843 passed`; statement coverage `98.86%`; branch
  coverage `96.47%`.
- Contract validation: schemas `85`, examples `136`, negative cases `101`,
  OpenAPI documents `7`.
- PostgreSQL and DGX providers were not invoked in this audit Slice.
