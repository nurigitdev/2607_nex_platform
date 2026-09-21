# Slice 0942: CX Retrieval Permission Decision Contract

## Goal

Define one fail-closed permission decision, filter result, snapshot, and evidence
contract for S95 before wiring persistent lexical and vector candidates.

## Implementation

- `CxAccessContext` is the sole identity source. Request payload
  `actor_claims_ref` data is not trusted as authorization input.
- `cx.private_owner_active.v1` permits only ACTIVE content whose tenant and
  owner subject exactly match the authenticated context.
- Missing, cross-owner, malformed-lineage, and inactive content all produce
  the same `RESOURCE_NOT_FOUND` decision.
- Explicit mixed scopes fail atomically with `cx.document_scope_not_found` and
  do not disclose the denied document identifier.
- Scope filtering deduplicates document IDs and records requested, visible,
  and denied document counts. Denied documents are never expanded into chunks,
  so their chunk count is neither loaded nor disclosed.
- Permission snapshots bind the authenticated OA user, tenant, applied visible
  IDs, classification, measured counts, and policy version.
- Evidence can be materialized only from a visible decision using the current
  policy version.

This Slice adds no table, migration, route, provider call, or persistent row.

## Verification

```bash
./.venv/bin/pytest -q \
  tests/test_nex_cx_retrieval_permissions.py \
  tests/test_cx_retrieval_permission_contract.py
./.venv/bin/python \
  scripts/smoke/run_cx_retrieval_permission_contract.py --summary
```

Observed on 2026-09-22:

- Focused permission suite: `23 passed`; new permission module and contract
  runner statement/branch coverage `100%`.
- Contract evidence: `PASS`, checks `8/8`, PostgreSQL required `False`, remote
  providers required `False`.
- Full quality gate: `6866 passed`; statement coverage `98.86%`; branch
  coverage `96.48%`.
- Contract validation: schemas `85`, examples `136`, negative cases `101`,
  OpenAPI documents `7`.
- PostgreSQL and DGX providers were not invoked in this contract Slice.
