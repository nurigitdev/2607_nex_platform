# Slice 0076 AG Retrieval Policy Registry

Status: Implemented.

Backlog candidate: `S8-001` AG retrieval policy read-only registry.

Requirement coverage: `AG-FR-001`, `CX-FR-003`, `CX-FR-004`,
`TRACE-CONTENT-001`, `PLAT-FR-007`.

## Scope

Slice 0076 adds a read-only retrieval policy registry under NeX-AG.

Endpoints:

- `GET /admin/v1/policies/retrieval`
- `GET /admin/v1/policies/retrieval/active`
- `GET /admin/v1/policies/retrieval/{policy_id}`

The registry exposes:

- current active policy: `retrieval_quality_v1`
- planned candidate policy: `weighted_rrf_vector_bm25_v1`

The current active policy matches Slice 0074 runtime behavior. The candidate
policy records the intended weighted RRF defaults: vector weight `0.7`, BM25
weight `0.3`, RRF `k=60`, and rerank candidate limit `50`.

## Safety

The AG projection includes policy IDs, versions, hashes, tokenizer profiles,
candidate limits, confidence thresholds, and provider aliases. It does not
include provider endpoint URLs, API keys, model paths, or raw document data.

Runtime mutation is intentionally not implemented in this slice. Policy update,
publish, rollback, and audit controls remain later work.

## Evidence

```bash
./.venv/bin/pytest tests/test_nex_ag_retrieval_policies.py
scripts/quality/run_quality_gate.sh
```
