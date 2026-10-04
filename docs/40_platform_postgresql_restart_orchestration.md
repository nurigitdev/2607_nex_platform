# Platform PostgreSQL Migration and Restart Orchestration

Status: S133 scope frozen; implementation in progress.

This document is the canonical non-drift record for S133. It connects the
typed S132 process topology to the five service-owned PostgreSQL test
databases without merging ownership, enabling remote providers, or claiming
the signed-trust work assigned to S134.

## Required Outcome

S133 must prove that:

- OA, MO, CX, AE, and AG test database configuration fails closed;
- all 89 versioned SQL migrations reach their service-local heads
  idempotently before process startup;
- each API and worker uses the correct service-owned database and separate
  pool settings;
- the protected `test` topology starts in dependency order and reaches
  database-backed readiness;
- coordinated shutdown disposes process and database resources;
- a fresh runtime instance restarts the topology and reloads durable state
  written independently to all five databases;
- cleanup leaves no S133 test residue and evidence never projects database
  passwords or complete database URLs.

The completion signal is: five test databases migrate and recover through a
protected restart smoke.

## Database Ownership

| Service | Test URL environment | Expected database | Expected role |
| --- | --- | --- | --- |
| OA | `NEX_OA_TEST_DATABASE_URL` | `nex_oa_test` | `nex_oa_user` |
| MO | `NEX_MO_TEST_DATABASE_URL` | `nex_mo_test` | `nex_mo_user` |
| CX | `NEX_CX_TEST_DATABASE_URL` | `nex_cx_test` | `nex_cx_user` |
| AE | `NEX_AE_TEST_DATABASE_URL` | `nex_ae_test` | `nex_ae_user` |
| AG | `NEX_AG_TEST_DATABASE_URL` | `nex_ag_test` | `nex_ag_user` |

The parent environment retains these test-specific names. Child processes
receive the corresponding service runtime `NEX_*_DATABASE_URL` alias in an
isolated environment. No database URL crosses a service boundary.

## Runtime Invariants

- Migration order is deterministic: OA, MO, CX, AE, then AG.
- Migrations run before any service process is spawned.
- Existing databases and tables are never dropped or reset by S133.
- API and worker engines remain separate and use `pool_pre_ping`.
- Restart means stop all processes, dispose owned engines, build a fresh
  runtime, and start all processes again. It is not an in-place process reuse.
- Readiness must use `/ready`; liveness alone cannot admit a protected process.
- AG continues to consume cross-service projections through service APIs.
- Background process shells may validate protected persistence lifecycle, but
  S133 does not activate unrelated business work claiming.

## Boundary-Time Foundation and Gaps

At the start of S133, the repository already had 89 service-owned migrations,
an all-service test profile migration runner, service database readiness
checks, separate API and worker pool settings, and the thirteen-process S132
topology.

The following boundary-time gaps drive the Slice sequence and remain here as
the non-drift checklist even after an individual gap is closed:

1. test database URLs are not yet projected to the active service child
   database environment names;
2. protected background process shells are blocked pending persistence wiring;
3. migration execution is not integrated with platform startup;
4. no coordinated stop/rebuild/restart controller exists;
5. no protected smoke proves durable state reload across all five databases.

## Requirement Boundary

S133 includes test-profile configuration, migration planning/execution,
database readiness, pool/session lifecycle, API and background process startup,
coordinated restart, durable sentinel reload, privacy-safe evidence, and
cleanup.

S133 does not include:

- production database credentials or production migration execution;
- OA signed-trust activation and rotation (`S134`);
- durable private document upload-to-index acceptance (`S135`);
- remote embedding, reranking, or generation acceptance (`S136`/`S137`);
- AG final generation-audit projection removal work (`S138`);
- browser golden journeys or release-candidate acceptance (`S139`/`S140`).

## Slice Sequence

1. `1322`: boundary, current-state audit, and non-drift guard.
2. `1323`: typed database orchestration evidence domain.
3. `1324`: five-service test database configuration and child aliases.
4. `1325`: migration-head and readiness orchestration.
5. `1326`: service-local pool/session lifecycle; Checkpoint Gate.
6. `1327`: protected API, worker, and daemon startup integration.
7. `1328`: coordinated shutdown and fresh-runtime restart state machine.
8. `1329`: durable five-database state restoration and cleanup contract.
9. `1330`: actual protected five-database restart smoke.
10. `1331`: S133 closure, S134 handoff, and Full Gate.

## S134 Handoff

S134 receives a restart-safe `test` topology whose PostgreSQL ownership,
migration heads, readiness, and pool lifecycle have been proven. S134 owns
signed service-token activation and trust-chain restart evidence. It must not
reopen database ownership or replace service-local persistence with a shared
database.

Any S133 scope change must update this document and
`37_platform_mvp_integration_release_plan.md` before implementation.
