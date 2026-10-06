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

## S134 Slice Plan

| Slice | Scope |
| --- | --- |
| `1332` | Freeze the S134 OA-backed user/session and signed service trust boundary. |
| `1333` | Adopt signed admission for OA internal user and session routes. |
| `1334` | Add explicit test-profile file-backed OA signing custody. |
| `1335` | Harden AE OA-backed signed login and downstream trust propagation. |
| `1336` | Define typed trust-chain evidence and privacy rules; run Checkpoint Gate. |
| `1337` | Integrate downstream signed scope and authorization denial flows. |
| `1338` | Orchestrate JWKS, introspection, revocation, and restart behavior. |
| `1339` | Execute the actual five-database loopback HTTP protected trust smoke. |
| `1340` | Harden contracts, privacy, cleanup, and the operations runbook. |
| `1341` | Close S134, publish the S135 handoff, and run Full Gate. |

S134 completion signal: Met. Slice 1339 proved the actual five-database,
two-generation loopback HTTP trust chain with zero seeded-row or temporary-key
residue. Slice 1340 froze the signed-login and active-claim contracts, privacy
rules, cleanup procedure, and operator runbook. Slice 1341 closed the evidence
and Full Gate while preserving the fail-closed default signer. S135 is the next
active requirement.

## S135 Slice Plan

| Slice | Scope |
| --- | --- |
| `1342` | Freeze the S135 authenticated upload-to-index boundary and S136 handoff. |
| `1343` | Fail closed on missing OA owner claims in protected AE upload profiles. |
| `1344` | Persist AE upload handoff metadata and owner-scoped readback in PostgreSQL. |
| `1345` | Harden CX upload idempotency and durable source, job, and run lineage. |
| `1346` | Hydrate restart-safe extraction, chunking, and BM25 worker state; run Checkpoint Gate. |
| `1347` | Publish a fresh owner-scoped vector index through MO mock embedding. |
| `1348` | Expose AE owner-scoped ingestion progress, failure, retry, and freshness. |
| `1349` | Coordinate restart recovery, cancellation safety, and cleanup. |
| `1350` | Execute the actual protected PostgreSQL authenticated upload-to-index smoke. |
| `1351` | Harden contracts and operations, close S135, and run Full Gate. |

S135 completion signal: Met. Slice 1350 proved an actual OA-authenticated
private document reaching lexical- and vector-index-ready state through signed
AE-to-CX HTTP and a durable worker, with owner-scoped restart readback and zero
database or file residue. Slice 1351 froze the progress/privacy contracts,
operator runbook, closure evidence, and Full Gate. S136 is the next active
requirement and owns live permission-filtered hybrid retrieval integration.

## S136 Slice Plan

| Slice | Scope |
| --- | --- |
| `1352` | Freeze the S136 live permission-filtered hybrid retrieval boundary and S137 handoff. |
| `1353` | Harden permission-first multi-document scope and denial evidence. |
| `1354` | Bind durable PostgreSQL BM25 and fresh pgvector candidate lineage. |
| `1355` | Freeze live embedding/reranker aliases, models, and request metadata. |
| `1356` | Harden weighted RRF and channel-contribution evidence; run Checkpoint Gate. |
| `1357` | Harden READY, LOW_CONFIDENCE, and NO_ANSWER semantics. |
| `1358` | Add metadata-only retrieval operations and provider-failure evidence. |
| `1359` | Add exact model-bound confidence calibration and reject unsafe raw-score threshold activation. |
| `1360` | Activate multi-signal calibration and prove PostgreSQL/live-provider retrieval, restart readback, denial isolation, and cleanup. |
| `1361` | Harden contracts/runbook, close S136, run Full Gate, and activate S137. |

S136 completion signal: Met. Actual `nex_cx_test`, Qwen3-Embedding-4B, and
Qwen3-Reranker-4B evidence passed permission-first BM25/pgvector retrieval,
weighted RRF, calibrated READY/LOW_CONFIDENCE/NO_ANSWER, restart readback,
denial isolation, and residue-free cleanup. Slice 1361 froze the handoff
contract and operator runbook and closed the Full Gate with `11,478 passed`,
`31` policy-skipped protected tests, statement coverage `98.06%`, and branch
coverage `96.99%`. S137 is the next active requirement and owns generation,
citation repair, and artifact lifecycle.

## S137 Slice Plan

| Slice | Scope |
| --- | --- |
| `1362` | Freeze the S137 grounded generation, repair, artifact lifecycle boundary and S138 handoff. |
| `1363` | Add owner-scoped restart-safe retrieval package materialization for generation. |
| `1364` | Compose retrieval admission, async generation, worker execution, and durable handoff. |
| `1365` | Bind citation validation and one bounded repair attempt to the exact package. |
| `1366` | Persist AE generated-response lineage and run the Checkpoint Gate. |
| `1367` | Connect verified response lineage to artifact admission and asynchronous rendering. |
| `1368` | Harden preview/download, restart recovery, cancellation, and owner isolation. |
| `1369` | Add contracts, operations evidence, and deterministic cross-service E2E. |
| `1370` | Execute protected PostgreSQL plus live generation-provider E2E evidence. |
| `1371` | Publish the runbook, close S137, run Full Gate, and activate S138. |

S137 completion signal: Met. Slice 1370 proved one authenticated and correlated
OA -> AE Web/API -> CX -> MO -> AE artifact journey against actual AE/CX test
databases and all three live provider capabilities, with restart-safe private
structured-draft and artifact readback, owner denial, and zero residue. Slice
1371 froze operations/privacy controls and closed the Full Gate with `11,641`
passed, `31` policy-skipped protected tests, statement coverage `98.06%`,
branch coverage `96.98%`, and S137 closure checks `15/15`. S138 is the next
active requirement and owns AG cross-service trace, audit, and operations E2E
through redacted service APIs only.

## S138 Slice Plan

| Slice | Scope |
| --- | --- |
| `1372` | Freeze the service-API-only S138 boundary, eight gaps, and S139 handoff. |
| `1373` | Define strict redacted stage-envelope and timeline contracts. |
| `1374` | Add CX ADMIN-scoped ingestion/retrieval/generation trace projection. |
| `1375` | Add AE upload/response/artifact trace projection. |
| `1376` | Add OA trust and MO provider trace projections. |
| `1377` | Add AG typed service-API clients and cross-service timeline aggregation. |
| `1378` | Persist redacted AG audit evidence and expose protected operations APIs. |
| `1379` | Prove deterministic success, failure, privacy, and restart scenarios. |
| `1380` | Prove the timeline against actual service test PostgreSQL databases. |
| `1381` | Publish the runbook, close S138, run Full Gate, and activate S139. |

S138 completion signal: Met. Slice 1380 proved all eight stage families through
authenticated service APIs against all five actual test PostgreSQL databases,
with `94` migrations current, restart-safe AG audit readback, no direct
cross-database reads, and zero fixture residue. Slice 1381 published the
operator runbook, composed all S138 evidence, and closed the Full Gate with
`11,784 passed`, `31 skipped`, statement coverage `98.08%`, branch coverage
`97.00%`, and closure checks `15/15`. S139 is the next active requirement and
owns Korean-default AE Web Playwright golden-journey acceptance.

## S139 Slice Plan

| Slice | Scope |
| --- | --- |
| `1382` | Freeze the S139 browser boundary, eight gaps, and S140 handoff. |
| `1383` | Define Korean-default, English-ready UI message and status contracts. |
| `1384` | Define the correlated golden-journey state and browser-safe evidence model. |
| `1385` | Integrate login, upload, and ingestion-progress browser acceptance. |
| `1386` | Integrate retrieval, generation, warning, citation, and repair acceptance; run Checkpoint Gate. |
| `1387` | Integrate artifact render, preview, and download acceptance. |
| `1388` | Harden desktop/mobile responsive, accessibility, and non-overlap acceptance. |
| `1389` | Execute deterministic two-viewport Playwright golden-journey acceptance. |
| `1390` | Execute protected browser plus service-process and test-PostgreSQL acceptance. |
| `1391` | Publish the runbook, close S139, run Full Gate, and activate S140. |

S139 completion signal: Met. Slice 1382 froze the browser-only same-origin
boundary and the requirement's eight acceptance gaps. Slice 1383 established
the Korean-default, English-ready message and status contract with exact
catalog parity. Slice 1384 froze one correlated nine-stage journey and
browser-safe evidence model. Slice 1385 connected OA login, claim-derived
upload ownership, and owner-scoped ingestion progress through `INDEX_READY`.
Slice 1386 extended the same journey through retrieval, generation, citation,
and repair acceptance and passed the fifth-Slice Checkpoint Gate. Slice 1387
completed the nine-stage deterministic journey through artifact render,
preview, and download with exact artifact-file lineage and content-free browser
evidence. Slice 1388 froze the shared desktop/mobile responsive, accessibility,
focus, overflow, and primary-region non-overlap contract before Chromium
execution. Slice 1389 then passed the deterministic nine-stage Korean journey
in actual Chromium at both frozen viewports, including visible login, upload,
generation, preview, and download actions with redacted evidence.
Slice 1390 composes the actual thirteen-process topology, OA-backed browser
login, owner-scoped upload, AE/CX PostgreSQL grounded artifact path, and both
Chromium viewports as one opt-in protected acceptance pack. Its five sources
passed with zero protected AE/CX fixture residue.
Remote model providers are not required for S139 closure;
S140 owns the final browser plus live-provider release-candidate matrix.
Slice 1391 published the operator runbook, aggregated eight deterministic PASS
components plus one protected opt-in SKIP, closed S139, and activated S140.
S140 is the next active requirement.

## S140 Slice Plan

| Slice | Scope |
| --- | --- |
| `1392` | Freeze the S140 release-candidate boundary, eight gaps, and non-production completion signal. |
| `1393` | Define typed release evidence, gate identities, and deterministic aggregation. |
| `1394` | Execute named deterministic `GEN-E2E-001` through `GEN-E2E-010`. |
| `1395` | Define protected admission for five test databases, three live providers, and two viewports. |
| `1396` | Re-run five-database migration, restart, restoration, and cleanup; run Checkpoint Gate. |
| `1397` | Execute live embedding, reranker, generation, calibration, and grounded-provider acceptance. |
| `1398` | Bind Korean browser evidence to AG trace, audit, and operations acceptance. |
| `1399` | Harden failure/recovery, privacy, zero-residue, and deployment-deferral evidence. |
| `1400` | Execute the complete protected release-candidate acceptance matrix. |
| `1401` | Publish the operator runbook, close S140, and run Full Gate. |

S140 completion signal: Pending. Slice 1392 freezes the RC boundary and does
not claim production deployment readiness.

Slice 1394 deterministic progress: `GEN-E2E-001` through `GEN-E2E-010` now
have one executable metadata-only aggregate runner. Protected database,
provider, browser, AG operations, and cleanup evidence remains pending.

Slice 1395 protected admission: the release-candidate profile now fails closed
unless all five test database identities, all three live provider capabilities,
the canonical provider profile, protected runtime modes, and both browser
viewports are configured. Admission performs no protected execution itself.

Slice 1396 protected database progress: the existing platform restart
orchestrator now emits typed `five_database_restart` RC evidence. A fresh run
passed migration twice, started thirteen processes in two generations,
restored and cleaned all five test-database sentinels, and confirmed zero
database residue. The fifth-Slice Checkpoint passed `11,270` tests at `98.91%`
statement and `97.29%` branch coverage.

Slice 1397 protected provider progress: a fresh run passed live embedding,
reranking, generation, twenty-sample multi-signal calibration, grounded
generation/artifact persistence, and cleanup with three capabilities and zero
residue. Model revision changes are accepted through runtime binding and
calibration rather than hard-coded release admission. Slice 1398 is next.

Slice 1398 protected browser/operations progress: the S139 actual-process
Korean Chromium journey passed both frozen viewports, and the S138
five-database AG service-API trace journey passed all eight stage families,
restart-safe audit, and zero combined residue. Slice 1399 is next.

## Protected Evidence Schedule

- `S131`: repository and deterministic regression evidence; no remote model
  provider is required.
- `S132`: local process and readiness evidence; mock provider mode is enough.
- `S133` to `S135`: actual service test databases are required.
- `S136`: actual embedding and reranker providers are required for closure.
- `S137`: actual generation provider is additionally required for closure.
- `S138`: actual service test databases are required; remote providers need
  not be called again solely to reconstruct the accepted S137 trace.
- `S139`: actual browser and service processes are required.
- `S140`: all test databases and all three remote provider capabilities are
  required for protected release-candidate evidence.

Any scope change must update this document first and explain the dependency or
evidence that caused the change.
