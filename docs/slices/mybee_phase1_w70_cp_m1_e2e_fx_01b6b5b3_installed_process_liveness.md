# CP-M1-E2E-FX-01B.6B.5B.3 Installed Process And Liveness

## Status

- Date: `2026-11-18`
- Status: `CLOSED`
- Parent amendment:
  `NeX_MyBee_CP_M1_E2E_FX_01B_6B_5B_Installed_WC_Assignment_Dispatch_Closure_v1.0.md`
- Database migration: none
- Remote provider: not required
- Next Slice: `CP-M1-E2E-FX-01B.6B.5B.4`

## Installed Boundary

WC now exposes `nex_wc.assignment_dispatch_process` as a package-checkable and
continuously runnable installed process. It composes the existing
`SqlAlchemyCoordinationRepository`, `WorkCoordinationService`,
`HttpAgentCandidateSource`, `HttpAuthorizationSource`, shared
`SqlAlchemyJobQueue`, heartbeat store, and service-log store. It does not add a
second routing policy, authorization decision, Assignment transaction, claim
handoff transport, or business table.

One process cycle deliberately performs two bounded phases:

1. discover and run eligible `CREATED -> ROUTED` work; and
2. rediscover and run eligible `ROUTED -> ASSIGNED` work.

The second phase uses persisted WC authority rather than in-memory output from
the first phase. A restart after the route commit therefore converges through
the same generic `ROUTED` scan. Claim-handoff publication remains owned by the
existing WC event-delivery worker.

## Operations Contract

- `--check` with package mode is offline and content-free;
- protected readiness verifies the current WC migration inventory and all
  required dispatch, queue, heartbeat, and service-log tables;
- test, staging, and production profiles use owner-local database variables;
- AE Registry and OA authorization clients require explicit signed service
  token configuration;
- one-cycle and continuous modes share the same scheduler/handler path;
- SIGINT/SIGTERM use first-request-wins graceful shutdown;
- STARTING, IDLE/ERROR, STOPPING, and STOPPED heartbeat states are persisted;
- the shared worker runner emits redacted service logs; and
- run and readiness records contain counts and states only, never WorkItem
  content, credentials, or lease material.

Compose, OCI, healthcheck command promotion, and deployed topology changes are
intentionally deferred to `.5B.4`.

## Restart Evidence

The protected PostgreSQL test creates a real WorkItem, commits only the route,
disposes the first engine and repository, and rebuilds the complete installed
process. The restarted process finds the durable `ROUTED` WorkItem, creates the
deterministic claim job, and reaches one active Assignment, Claim, and handoff
outbox. The smoke also verifies persisted heartbeat and service-log evidence,
then removes all test-owned business rows.

## Verification

- focused process/scheduler regression with actual WC PostgreSQL: `36 passed`
- actual database identity: `nex_wc_test / nex_wc_user`
- actual migration inventory: `14 / 14`, no missing or unexpected migration
- protected readiness: `READY`
- protected one-cycle run: `STOPPED`, `MAX_CYCLES`, zero failures
- restart path: `CREATED -> ROUTED`, engine/repository restart,
  `ROUTED -> ASSIGNED`
- package source check: PASS, database not requested
- Ruff, Black, compile, and diff checks: PASS
- WC Slice Gate: `729 passed`, `25 protected skips`
  - statement coverage: `98.18%`
  - branch coverage: `96.03%`
  - commands: `5/5`
- contract validation: `274 schemas`, `320 examples`, `260 negative examples`,
  `10 OpenAPI`
- Golden Journey transition and demo/product dependency audits: PASS
- evidence:
  `reports/quality/mybee-w70-cp-m1-01b6b5b3-wc-slice-gate.json`

The non-blocking Starlette/httpx and SQLite datetime deprecation warnings are
unchanged. No generation, embedding, or reranking provider was contacted.

## Closure

`CP-M1-E2E-FX-01B.6B.5B.3` is closed. The generic assignment dispatcher now
has source admission, protected readiness, one-cycle and continuous execution,
heartbeat, service logging, graceful shutdown, and restart recovery. The
process remains deployment-inactive until `.5B.4` promotes its Compose, OCI,
and topology bindings.
