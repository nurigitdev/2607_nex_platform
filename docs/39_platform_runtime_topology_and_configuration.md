# Platform Runtime Topology and Configuration

Status: S132 scope frozen; implementation in progress.

This document is the canonical non-drift record for S132. It translates the
S131 re-audit into one explicit local runtime topology without changing service
ownership or claiming the PostgreSQL and provider evidence assigned to later
requirements.

## Required Outcome

S132 must provide one typed manifest that describes:

- five backend APIs and AE Web;
- required worker and daemon processes;
- ports, public service URLs, commands, and environment ownership;
- profile-aware provider, persistence, trust, and AG projection modes;
- dependency ordering and liveness/readiness probes;
- bounded startup, shutdown, and CX-to-MO timeout budgets;
- a privacy-safe machine-readable process status projection.

The complete `local_mock` topology must start and stop from this manifest.
Protected profiles must reject missing trust, database, provider, or service
endpoint settings before spawning a process.

## Ownership Invariants

- OA remains the identity and trust owner.
- AE owns workspace and artifact state.
- CX owns private content, retrieval, and grounded-generation lineage.
- MO exclusively owns remote provider endpoints and credentials.
- AG consumes service APIs for cross-service projections. Legacy direct
  database projection code may remain temporarily for compatibility tests, but
  no S132 protected profile may select it.
- Each service retains its own database. The runtime manifest carries database
  environment variable names, never database credentials or URLs.

## Profile Invariants

| Profile | Persistence | Providers | Trust | AG projection |
| --- | --- | --- | --- | --- |
| `local_mock` | memory | mock | test mock | memory/API mock |
| `test` | PostgreSQL test DBs | mock | signed | service API |
| `local_live` | PostgreSQL dev DBs | live through MO | signed | service API |
| `staging_live` | PostgreSQL | live through MO | signed | service API |
| `production` | PostgreSQL | live through MO | signed | service API |

`local_mock` remains deterministic and needs neither PostgreSQL nor DGX.
Every other profile is protected and fails closed when required configuration
is absent, placeholder-valued, contradictory, or selects cross-service DB
projection mode.

## Requirement Boundary

S132 includes topology, validation, process definitions, dependency-aware
startup, readiness reporting, actual local mock process evidence, and a
rollback path to the former five-service runner.

S132 does not include:

- applying or restarting the five PostgreSQL test databases (`S133`);
- proving the OA signed trust chain (`S134`);
- durable upload/index behavior (`S135`);
- live embedding, reranking, or generation evidence (`S136`/`S137`);
- the final CX admin generation-audit projection (`S138`);
- browser golden-journey acceptance (`S139`);
- release-candidate acceptance (`S140`).

## Slice Sequence

1. `1312`: boundary and non-drift guard.
2. `1313`: typed runtime manifest domain.
3. `1314`: fail-closed profile composition.
4. `1315`: dependency and readiness graph.
5. `1316`: endpoints and timeout policy; Checkpoint Gate.
6. `1317`: complete process manifest.
7. `1318`: AG service-API-only policy.
8. `1319`: readiness-gated orchestrator and status.
9. `1320`: actual `local_mock` process smoke.
10. `1321`: closure and Full Gate.

## Implementation State

| Slice | Status | Evidence |
| --- | --- | --- |
| `1312` | Complete | S132 boundary and non-drift guard are frozen. |
| `1313` | Complete | Typed manifest validation and safe projection pass. |
| `1314` | Complete | Five profiles compose; protected profiles fail closed. |
| `1315` | Complete | Dependency order and profile-aware probes validate. |
| `1316` | Complete | Endpoints, retry-aware timeout budgets, canonical aliases, and Checkpoint Gate pass. |
| `1317`-`1321` | Pending | Process manifest, AG API-only projection, orchestrator, local process smoke, and closure remain. |

Any S132 scope change must update this document and
`37_platform_mvp_integration_release_plan.md` before implementation.
