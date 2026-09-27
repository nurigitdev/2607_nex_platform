# Slice 0992: CX MVP Integration and AE Handoff Boundary Audit

## Goal

Freeze the S100 boundary before connecting the completed CX capabilities into
the production bootstrap and exposing an owner-safe asynchronous generation
handoff to AE.

## Findings

- Durable ingestion, hardened hybrid retrieval, atomic pgvector publish,
  asynchronous generation, restart-safe reads, and resilient workers exist as
  tested foundations.
- The production CX bootstrap still registers the legacy retrieval path because
  the hardened hybrid runtime is assembled only by protected smoke code.
- Durable ingestion still writes the legacy embedding-index representation and
  does not automatically publish the S94 freshness-guarded pgvector index.
- S99 exposes admission, job polling, and cancellation, but AE lacks one
  owner-safe projection that joins terminal job state with the persisted
  generation result.
- Citation repair planning exists, but the grounded-generation worker does not
  yet execute one bounded repair attempt against the same retrieval package.

## Frozen Decisions

- Preserve the explicit upload, retrieval, and generation-job APIs. S100 does
  not add a monolithic endpoint that hides service boundaries.
- Production retrieval must use the permission-first S95 hybrid runtime.
- Durable ingestion publishes an owner-scoped, freshness-checked pgvector index
  without storing vectors or private chunk text in public metadata rows.
- AE receives an owner-safe pollable handoff projection; cross-owner resources
  remain indistinguishable from missing resources.
- Citation repair is limited to one bounded repair attempt and must reuse the
  admitted retrieval package and evidence set.
- S100 adds no database table. Existing CX metadata, job, private payload, and
  vector storage boundaries remain canonical.
- CX reaches embedding, reranking, and generation providers only through NeX-MO
  capability aliases. Protected PostgreSQL and live-provider proof belongs to
  Slice 1000.
- Streaming, shared/group ACL, multi-document scale tuning, and production
  provider SLO baselines remain deferred.

## Slice Plan

1. `0992`: boundary audit.
2. `0993`: CX MVP lifecycle contract.
3. `0994`: production hardened hybrid retrieval composition.
4. `0995`: durable ingestion vector publish wiring.
5. `0996`: AE generation handoff projection and Checkpoint Gate.
6. `0997`: bounded citation repair.
7. `0998`: production runtime composition.
8. `0999`: contract, OpenAPI, privacy, and observability hardening.
9. `1000`: actual `nex_cx_test` plus DGX end-to-end smoke.
10. `1001`: S100 closure and Full Gate.

## Verification

```bash
scripts/quality/run_slice_gate.sh --service nex-cx \
  --test tests/test_cx_mvp_integration_ae_handoff_boundary_audit.py \
  --coverage-target scripts/smoke/run_cx_mvp_integration_ae_handoff_boundary_audit.py \
  --smoke scripts/smoke/run_cx_mvp_integration_ae_handoff_boundary_audit.py
```

The audit itself performs no database, filesystem payload, or provider call.

## Observed Evidence

- Slice Gate: `2,110 passed`.
- Repository statement coverage: `98.99%`.
- Repository branch coverage: `98.02%`.
- Boundary audit statement/branch coverage: `100%`/`100%`.
- Contract validation: `91` schemas, `142` positive examples, `107` negative
  examples, and `7` OpenAPI documents.
- Audit result: foundations `8`, gaps `8`, open `8`, issues `0`, next Slice
  `0993`.
