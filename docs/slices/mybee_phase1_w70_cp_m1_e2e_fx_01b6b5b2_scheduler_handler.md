# CP-M1-E2E-FX-01B.6B.5B.2 Generic Scheduler And Handler

## Status

- Date: `2026-11-18`
- Status: `CLOSED`
- Parent amendment:
  `NeX_MyBee_CP_M1_E2E_FX_01B_6B_5B_Installed_WC_Assignment_Dispatch_Closure_v1.0.md`
- Database migration: none
- Remote provider: not required
- Next Slice: `CP-M1-E2E-FX-01B.6B.5B.3`

## Product Boundary

The WC-local scheduler now reads only the bounded, state-specific claimable
source admitted by `.5B.1`. It creates deterministic
`WC_ASSIGNMENT_DISPATCH` jobs through the shared `JobQueue` contract. Repeated
scheduler cycles return the same idempotent job identity and do not duplicate
work. Scheduler summaries contain only action, counts, job IDs, and the next
keyset cursor; WorkItem goal and business content are not projected.

The generic handler validates the job and reloads current WC authority before
performing an action. It delegates all business transitions to the existing
`WorkCoordinationService.route()` and `claim()` methods. The handler does not
implement a second routing policy, candidate selector, OA authorization path,
assignment transaction, or handoff publisher.

## Failure And Replay Semantics

- successful `ROUTE` and `CLAIM` jobs complete through the shared
  `run_worker_once()` lifecycle;
- no eligible Agent and unavailable dependencies remain retryable and use the
  shared bounded backoff policy;
- version conflicts trigger one authority reload;
- a route committed before ACK loss is returned as `ROUTE_REPLAYED`;
- a claim committed before ACK loss is reconstructed from the active
  assignment, claim, and claim-handoff outbox as `CLAIM_REPLAYED`;
- unresolved stale authority, malformed jobs, missing WorkItems, and policy or
  authorization denials are terminal dead letters; and
- result projections never expose the Claim lease token or verifier.

The exact-claim replay query reuses `wc_assignment`, `wc_claim`, and
`wc_event_outbox`. It adds no new table or mutable business state. Incomplete
or inactive authority chains fail closed and cannot be treated as successful
replay.

## Verification

- focused scheduler, handler, coordination regression: `61 passed`,
  `2 protected skips`
- actual WC PostgreSQL regression: `39 passed`
- actual database identity: `nex_wc_test / nex_wc_user`
- actual path: scheduler `CREATED -> ROUTE`, scheduler `ROUTED -> CLAIM`,
  repository restart, exact claim replay
- protected test residue: `0`
- Ruff, compile, and diff checks: PASS
- WC Slice Gate: `705 passed`, `24 protected skips`
  - statement coverage: `98.05%`
  - branch coverage: `95.94%`
  - commands: `5/5`
- contract validation: `274 schemas`, `320 examples`, `260 negative examples`,
  `10 OpenAPI`
- Golden Journey transition and demo/product dependency audits: PASS
- evidence:
  `reports/quality/mybee-w70-cp-m1-01b6b5b2-wc-slice-gate.json`

The non-blocking Starlette/httpx and SQLite datetime deprecation warnings are
unchanged. No remote generation, embedding, or reranking provider was used.

## Closure

`CP-M1-E2E-FX-01B.6B.5B.2` is closed. WC now has a generic scheduler and
handler over the shared queue and authoritative coordination service. This
Slice intentionally does not add a continuous daemon, installed dependency
composition, service logs, shutdown handling, Compose, or OCI wiring. Those
process and liveness responsibilities remain assigned to `.5B.3`.
