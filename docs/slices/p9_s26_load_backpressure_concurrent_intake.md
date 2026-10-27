# P9-S26: Load, Backpressure, and Concurrent Intake

## Scope

NeX-WA retains PostgreSQL `service_jobs` as the Foundation queue. No external
broker or second authority was introduced. API intake and evidence consumers
now use separate `SqlAlchemyJobQueue` adapters backed by the existing API and
worker pools respectively, while sharing the same durable Job table.

Concurrent first delivery of the same deterministic source identity now
recovers the committed winner after a unique conflict. Recovery is accepted
only when the deterministic Job is durably readable and semantically
compatible; otherwise intake returns retryable `503
WA_INTAKE_STORE_UNAVAILABLE`. This changes neither source authority nor source
business state.

## Protected Load Gate

The actual `nex_wa_test` gate covers:

- `100` distinct concurrent durable intake requests
- an additional same-source first-enqueue race
- at least `2` concurrent consumer instances
- PostgreSQL `FOR UPDATE SKIP LOCKED` claim isolation
- one Job, WorkEvidence, WorkAsset, and primary binding per source revision
- queue depth before and after consumer drain
- bounded API and worker pool high-water marks
- intake p95 target of `500 ms`
- scoped cleanup and zero residue

Remote generation, embedding, and reranking providers are outside this Slice.

## Evidence

- focused regression: `52 passed`
- actual `nex_wa_test` protected load smoke: `1 passed`
- concurrent intake requests: `100`
- resulting semantic Jobs/Evidence/Assets: `101 / 101 / 101`, including the
  same-source first-enqueue race
- concurrent consumer claims: `51 / 50`
- measured intake p95: `336.699 ms` against the `500 ms` target
- API pool high-water mark: `12 / 12`
- worker pool high-water mark: `2 / 6`
- scoped PostgreSQL cleanup and zero residue: `PASS`
- NeX-WA Slice Gate: `285 passed`, `11 skipped`
- statement coverage: `97.15%`
- branch coverage: `94.14%`
- contract validation: `226` schemas, `290` examples, `241` negative
  examples, and `10` OpenAPI documents
