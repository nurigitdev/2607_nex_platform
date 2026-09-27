# Slice 0993: CX MVP Lifecycle Contract

## Goal

Define one metadata-only lifecycle contract that consistently describes CX
progress from durable ingestion through AE generation handoff.

## Implementation

- Added `cx_mvp_integration.v1` with owner-scoped deterministic identity.
- Projects ingestion, vector-index, retrieval, generation-job, and generation
  summaries into stable `stage`, `status`, and `next_action` values.
- Component references accept only bounded IDs, statuses, and required hashes;
  private text, vectors, paths, endpoints, credentials, and arbitrary fields
  cannot enter the projection.
- Covers retry/rebuild/retrieval-revision/generation-repair decisions without
  collapsing the existing service-local APIs into a monolithic endpoint.
- Adds no table or migration. Later S100 adapters will assemble this contract
  from existing persisted records.

## Verification

```bash
scripts/quality/run_slice_gate.sh --service nex-cx \
  --test tests/test_nex_cx_mvp_integration.py \
  --coverage-target services/nex-cx/nex_cx/mvp_integration.py
```

## Observed Evidence

- Slice Gate: `2,138 passed`.
- Repository statement coverage: `98.98%`.
- Repository branch coverage: `98.04%`.
- Lifecycle contract branch coverage: `100%`; focused follow-up confirms the
  exception-string path and raises statement coverage to `100%`.
- Contract validation: `91` schemas, `142` positive examples, `107` negative
  examples, and `7` OpenAPI documents.
- Boundary audit: resolved gaps `1/8`, next Slice `0994`.
