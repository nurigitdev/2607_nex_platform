# Slice 1353: CX Permission-First Scope Hardening

## Goal

Preserve owner/tenant denial as a safe not-found response and prove that a
mixed authorized/unauthorized document scope cannot reach candidate or private
payload dependencies.

## Implementation

- The hybrid package boundary now maps `RetrievalPermissionError` to a
  non-retryable 404 instead of misclassifying it as a retryable 503 provider
  failure.
- Added a mixed-owner regression proving that content metadata is the only
  dependency touched before denial. Query embedding, BM25, pgvector, private
  text, and reranking remain untouched.
- Denial detail remains generic and does not echo the foreign document ID.
- Added repository evidence for the permission-first call order.

No table, migration, route, provider call, or payload schema was added.

## Verification

```bash
scripts/quality/run_slice_gate.sh --service nex-cx \
  --test tests/test_cx_permission_first_scope_hardening.py \
  --coverage-target services/nex-cx/nex_cx/hybrid_retrieval_package.py \
  --coverage-target scripts/smoke/run_cx_permission_first_scope_hardening.py \
  --smoke scripts/smoke/run_cx_permission_first_scope_hardening.py
```
