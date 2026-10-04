# Platform MVP Integration and Release Plan

Status: Canonical scope freeze for requirements S131 through S140.

This plan follows the service-level MVP closures completed through S130. It
freezes the next requirement sequence so implementation details can evolve
without drifting away from the intended platform outcome.

## Program Outcome

S131 through S140 connect the independently proven OA, AE, CX, MO, and AG
capabilities into one restart-safe, permission-filtered, observable MVP
vertical spine. The phase ends with a release-candidate decision; it does not
claim production deployment controls such as external key custody, managed
TLS, secret injection, or enterprise IdP registration.

## Frozen Requirement Sequence

| Requirement | Name | Core Scope | Completion Signal |
| --- | --- | --- | --- |
| `S131` | Platform MVP vertical-spine current-state re-audit and integration boundary checkpoint | Re-audit OA -> AE Web/API -> CX -> MO -> AG implementation, API calls, mock residue, direct calls, persistence, traceability, and refactoring needs. | A repository-grounded gap inventory and S132 handoff are complete. |
| `S132` | Platform multi-service runtime topology and configuration hardening | Standardize ports, startup order, environment profiles, readiness dependencies, service URLs, and mock/live selection. | All backend services start from one explicit local runtime profile with fail-closed configuration. |
| `S133` | Cross-service PostgreSQL migration, startup, and restart orchestration | Coordinate service-owned test migrations, pool readiness, startup, shutdown, restart, and durable reload. | Five test databases migrate and recover through a protected restart smoke. |
| `S134` | OA-backed user and service trust end-to-end integration | Carry OA user sessions, signed service tokens, scopes, JWKS/introspection, and denial behavior across AE, CX, MO, and AG. | One actual signed trust chain passes and revoked/unauthorized requests fail closed. |
| `S135` | Authenticated document upload-to-index durable journey | Connect AE upload to CX source storage, extraction, Markdown, chunking, BM25, embedding freshness, jobs, and progress. | A private document reaches index-ready state with restart-safe lineage. |
| `S136` | Permission-filtered hybrid retrieval live integration | Exercise owner/tenant filtering, BM25, vector search, weighted RRF, reranking, confidence, and no-answer behavior. | Protected PostgreSQL plus embedding/reranker evidence passes without cross-owner leakage. |
| `S137` | Grounded generation, repair, and artifact lifecycle E2E | Connect retrieval packages, CX generation, MO generation, citation validation/repair, AE lineage, rendering, preview, and download. | Grounded answer and artifact scenarios preserve evidence and recovery lineage. |
| `S138` | AG cross-service trace, audit, and operations E2E | Project the same trace through auth, upload, ingestion, retrieval, generation, artifact, failures, and operator evidence. | AG reconstructs a redacted service-API-only timeline for the golden journey. |
| `S139` | AE Web Korean-default Playwright golden-journey acceptance | Verify browser login, upload, progress, retrieval, generation, warnings, citations, preview, and download in the Korean-default UI. | Protected Playwright acceptance passes on desktop and mobile viewports. |
| `S140` | Platform MVP release-candidate acceptance and operations closure | Execute GEN-E2E-001 through GEN-E2E-010, PostgreSQL, restart, live providers, browser, contracts, privacy, and Full Gate evidence. | MVP RC gates pass with zero database/file residue and explicit deployment deferrals. |

## Non-Drift Rules

- OA remains the identity and trust owner; other services validate OA-issued
  user or service identity without reading the OA database.
- AE owns the user workspace and artifacts. CX owns document semantics,
  retrieval, and grounded generation lineage. MO owns provider routing and
  runtime metadata. AG reads service APIs and owns only operator projections.
- AE and AG never call model providers directly. CX reaches providers only
  through MO capability aliases.
- Test databases are used for protected PostgreSQL evidence. Mock providers
  remain the deterministic regression baseline; live providers are additional
  protected evidence for S136, S137, and S140.
- Cross-service integration must use HTTP/API contracts or explicit client
  ports. Shared database reads are prohibited.
- A requirement starts with structure and boundary review. Refactoring needed
  to expose a clean port precedes new orchestration behavior.
- Slice Gate runs for each Slice, Checkpoint Gate on the fifth Slice, and Full
  Gate on the closure Slice. Existing thresholds and rollback commands remain
  unchanged.

## S131 Slice Plan

| Slice | Scope |
| --- | --- |
| `1302` | Freeze S131-S140 and establish the vertical-spine audit boundary. |
| `1303` | Inventory cross-service routes, clients, and call topology. |
| `1304` | Audit runtime profiles, mock residue, and direct-call risks. |
| `1305` | Audit OA-to-AE user and service trust propagation. |
| `1306` | Audit AE-to-CX upload, retrieval, and generation paths; run Checkpoint Gate. |
| `1307` | Audit CX-to-MO provider execution and alias boundaries. |
| `1308` | Audit AE artifact handoff and AG trace/audit projections. |
| `1309` | Audit persistence, jobs, restart behavior, and process orchestration. |
| `1310` | Audit contracts, trace propagation, privacy, and GEN-E2E acceptance gaps. |
| `1311` | Close S131, publish the prioritized refactoring inventory, and run Full Gate. |

## S132 Slice Plan

| Slice | Scope |
| --- | --- |
| `1312` | Freeze the S132 runtime-topology boundary, completion signal, and S133 handoff. |
| `1313` | Define the typed platform runtime manifest domain and safe public projection. |
| `1314` | Compose explicit runtime profiles and reject incomplete protected configuration. |
| `1315` | Validate dependency ordering and profile-aware liveness/readiness probes. |
| `1316` | Centralize service endpoints and enforce safe CX-to-MO timeout budgets; run Checkpoint Gate. |
| `1317` | Materialize the five APIs, AE Web, required workers, and daemons as typed processes. |
| `1318` | Require service-API projection mode in protected profiles and quarantine legacy AG database reads. |
| `1319` | Add readiness-gated process orchestration and machine-readable runtime status. |
| `1320` | Start and stop the complete `local_mock` topology in an actual protected process smoke. |
| `1321` | Close S132, publish the S133 handoff, and run Full Gate. |

S132 completion signal: Met. All backend services start from one explicit
local runtime profile with fail-closed configuration. S133 is the next active
requirement and owns actual five-database migration and restart evidence.

## S133 Slice Plan

| Slice | Scope |
| --- | --- |
| `1322` | Freeze the S133 database orchestration boundary, completion signal, and S134 handoff. |
| `1323` | Define typed migration, readiness, pool, restart, and restoration evidence. |
| `1324` | Compose five service-owned test database targets and isolated child aliases. |
| `1325` | Orchestrate idempotent migration heads and database readiness before startup. |
| `1326` | Harden API/worker pool and session lifecycle; run Checkpoint Gate. |
| `1327` | Start protected APIs, workers, and daemons against service-owned test databases. |
| `1328` | Add coordinated shutdown and fresh-runtime restart orchestration. |
| `1329` | Add durable five-database state restoration and residue-free cleanup evidence. |
| `1330` | Execute the actual protected five-database migration/start/restart smoke. |
| `1331` | Close S133, publish the S134 handoff, and run Full Gate. |

S133 completion signal: Met. All five service-owned test databases reach their
89 migration heads and recover committed state through a protected restart of
the thirteen-process topology. The smoke rebuilds ten fresh pools, leaves zero
S133 sentinel rows, and does not contact remote model providers. S134 is the
next active requirement and inherits this restart-safe test topology.

## Protected Evidence Schedule

- `S131`: repository and deterministic regression evidence; no remote model
  provider is required.
- `S132`: local process and readiness evidence; mock provider mode is enough.
- `S133` to `S135`: actual service test databases are required.
- `S136`: actual embedding and reranker providers are required for closure.
- `S137`: actual generation provider is additionally required for closure.
- `S139`: actual browser and service processes are required.
- `S140`: all test databases and all three remote provider capabilities are
  required for protected release-candidate evidence.

Any scope change must update this document first and explain the dependency or
evidence that caused the change.
