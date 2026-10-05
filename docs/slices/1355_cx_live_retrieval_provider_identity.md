# Slice 1355: CX Live Retrieval Provider Identity

## Goal

Preserve privacy-safe live embedding and reranker identity through the CX
hybrid retrieval package.

## Implementation

- Query embedding now returns the vector plus bounded provider alias, model
  revision, and deployment ID metadata.
- The hybrid candidate set carries that profile beside the query-vector hash;
  the retrieval package projects it under `retrieval_profile.embedding_profile`.
- Existing reranker alias/model/deployment projection remains the matching
  rerank identity boundary.
- Endpoint URLs, API keys, raw vectors, query text, and private chunk text are
  not added to the provider profile or persistence preview.
- Protected live acceptance expects canonical aliases `embedding-default` and
  `reranker-default`, Qwen3-Embedding-4B, and Qwen3-Reranker-4B. MO's legacy
  `mock-*` aliases remain compatibility internals and are not removed here.

No table, migration, or route was added. Actual provider identity is asserted
by the Slice 1359 protected live smoke.

## Verification

```bash
scripts/quality/run_slice_gate.sh --service nex-cx \
  --test tests/test_cx_live_retrieval_provider_identity.py \
  --coverage-target services/nex-cx/nex_cx/hybrid_retrieval_runtime.py \
  --coverage-target services/nex-cx/nex_cx/hybrid_retrieval_package.py \
  --coverage-target scripts/smoke/run_cx_live_retrieval_provider_identity.py \
  --smoke scripts/smoke/run_cx_live_retrieval_provider_identity.py
```
