# Slice 0947: CX Hybrid Retrieval Package API and Persistence Wiring

## Goal

Wire the permission-first candidate and privacy-safe ranking path from Slices
0942-0946 into the canonical CX retrieval package API while preserving owner
lineage and preventing private query or evidence previews from entering the
persistence record.

## Implementation

- Adds `PermissionFilteredHybridPackageRuntime`, which validates an explicit
  document scope, obtains permission-admitted hybrid candidates, applies the
  canonical weighted RRF/rerank boundary, and materializes only exact
  owner-authorized evidence.
- Revalidates evidence identity and SHA-256 lineage before constructing the
  existing `cx_retrieval_context_package.v1` response.
- Injects the hardened runtime into the canonical
  `POST /api/v1/retrieval/context` route without changing the legacy fallback.
- Retains `ContentIngestionStore.save_retrieval_package` as the single
  write-through boundary and the existing GET package read path.
- Marks hardened packages with `hash_only_private_owner`. Persistence retains
  query/evidence SHA-256 values while setting both private text previews to
  `NULL`; legacy package preview behavior remains compatible.
- Adds deterministic contract evidence for authenticated API execution,
  owner/permission lineage, package read-back, deterministic identity, and
  hash-only persistence conversion.
- Adds no table or migration. Actual PostgreSQL plus remote embedding/reranker
  composition remains reserved for the protected Slice 0949 smoke.

## Verification

```bash
./.venv/bin/pytest -q \
  tests/test_nex_cx_hybrid_retrieval_package.py \
  tests/test_nex_cx_retrieval_persistence.py \
  tests/test_nex_cx_retrieval.py \
  tests/test_cx_hybrid_retrieval_package_contract.py \
  --cov=nex_cx.hybrid_retrieval_package \
  --cov=run_cx_hybrid_retrieval_package_contract \
  --cov-branch --cov-report=term-missing
```

Focused results:

- `138 passed`.
- Hybrid retrieval package runtime statement/branch coverage: 100%/100%.
- Contract runner statement/branch coverage: 100%/100%.
- Deterministic contract evidence: `10/10` checks passed.

Full quality-gate results:

- `7111 passed`.
- Repository statement coverage: 98.87%.
- Repository branch coverage: 96.54%.
- Contract validation: 85 JSON Schemas, 136 examples, 101 negative examples,
  and 7 OpenAPI documents passed.

PostgreSQL and remote embedding/reranker access were intentionally not invoked
and remain deferred to the protected Slice 0949 smoke.
