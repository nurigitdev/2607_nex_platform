# Platform PostgreSQL Migration and Restart Orchestration

Status: S133 complete; S134 handoff frozen.

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

## Implementation State

| Slice | Status | Evidence |
| --- | --- | --- |
| `1322` | Complete | Five-database ownership, completion signal, and non-drift boundary are frozen. |
| `1323` | Complete | Typed orchestration plan and privacy-safe per-service evidence validate. |
| `1324` | Complete | Five test targets, role/database identity, and isolated child aliases fail closed. |
| `1325` | Complete | All 89 migration heads, ledgers, identities, and readiness checks pass on actual test databases. |
| `1326` | Complete | Ten distinct API/worker pools and sessions dispose cleanly and rebuild fresh. |
| `1327` | Complete | Five APIs and seven background shells start against actual service-owned test databases. |
| `1328` | Complete | Migration-gated startup, reverse shutdown, and one fresh restart generation pass. |
| `1329` | Complete | Five durable sentinels restore and clean through 20 fresh PostgreSQL connections. |
| `1330` | Complete | Thirteen processes restart across two generations with 10+10 pools and zero residue. |
| `1331` | Complete | S133 acceptance, S134 handoff, and repository Full Gate pass. |

## Completion

Completion signal: Met.

The protected restart smoke applied and verified all 89 migrations on the five
service-owned test databases, started all thirteen processes, stopped them in
reverse dependency order, disposed ten pools, rebuilt ten fresh pools, and
started all thirteen processes again. Five committed sentinels were restored
after restart and then removed; direct post-smoke counts were zero in every
test database. No remote model provider was contacted and no business job was
claimed.

## S134 Handoff

S134 receives a restart-safe `test` topology whose PostgreSQL ownership,
migration heads, readiness, and pool lifecycle have been proven. S134 owns
signed service-token activation and trust-chain restart evidence. It must not
reopen database ownership or replace service-local persistence with a shared
database.

S134 is the next active requirement. It must replace the startup-only
synthetic trust values with OA-issued user sessions and signed service tokens,
exercise JWKS/introspection and scope enforcement across AE, CX, MO, and AG,
and prove revocation and unauthorized denial across a restart. It inherits the
S133 database and process orchestration unchanged.

Any S133 scope change must update this document and
`37_platform_mvp_integration_release_plan.md` before implementation.
