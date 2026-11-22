# NeX MyBee CP-M1-E2E-FX-01B.6B.5B: Installed WC Assignment Dispatch Closure v1.0

## 1. Status And Authority

- Decision date: 2026-11-18
- Status: DESIGN_CLOSED_IMPLEMENTATION_REQUIRED
- Repository: nurigitdev/2607_nex_platform
- Branch: codex/mybee-phase1-implementation
- Source-backed review commit: 39e54477
- Parent amendment:
  `NeX_MyBee_CP_M1_E2E_FX_01B_Durable_Business_Context_and_M1_Transaction_Orchestration_Closure_v1.0.md`
- Predecessor: `CP-M1-E2E-FX-01B.6B.5A.5`
- Suspended successor: `CP-M1-E2E-FX-01B.7`
- Runtime code changes by this document: none
- Database migration authorized after source-backed review:
  `1007_wc_assignment_dispatch_scan`
- Remote model-provider dependency: none
- New installed process authorized by this document: one generic WC assignment
  dispatcher

This controlled amendment closes the installed transition gap between a
durable WC WorkItem and the existing WC claim-handoff delivery boundary. A
public AE delegation currently creates a `CREATED` WorkItem, while the
installed topology has no process that performs the existing authoritative
`CREATED -> ROUTED -> ASSIGNED` transitions. Smoke and component tests can
call route and claim directly, but a protected runner must not own those
product transitions.

The closure SHALL add one provider-neutral, product-neutral WC assignment
dispatcher process. It SHALL reuse the existing WC routing, claim,
authorization, outbox, JobQueue, worker lifecycle, heartbeat, packaging, and
deployment primitives. It SHALL NOT create an M1 dispatcher, a Project
dispatcher, a second routing policy, a second authorization decision, or a
fixture-backed shortcut.

## 2. Source-Backed Entry Findings

### 2.1 Public Delegation Stops At CREATED

`services/nex-ae-api/nex_ae_api/step_executors.py` creates the WC WorkItem and
accepts only the initial `CREATED` state before returning a durable wait. This
is the correct producer boundary: AE delegates work but does not own WC
routing or claim authority.

### 2.2 WC Already Owns Route And Claim Authority

`services/nex-wc/nex_wc/coordination.py` already implements both transitions:

- `WorkCoordinationService.route()` loads a `CREATED` WorkItem, obtains
  candidates from the existing AE Agent Registry source, applies the existing
  `RoutingPolicy`, and stores the routing decision with optimistic version
  control;
- `WorkCoordinationService.claim()` reloads the selected agent, validates the
  current candidate, obtains fresh effective authorization from OA, requires
  `work:claim`, and atomically stores Assignment, Claim, claim handoff, and WC
  outbox authority.

The dispatcher therefore SHALL call these service methods. Reimplementing
candidate selection, OA authorization, Assignment, Claim, or outbox mutation
inside the process is prohibited.

### 2.3 Installed Topology Has Delivery But No Assignment Dispatcher

`services/_shared/nex_runtime/current_platform_installation.py` admits the AE
Agent Runtime worker, WC event-delivery worker, and EOS outbox publisher. It
does not admit a WC process that discovers and advances assignment work.

`services/nex-wc/nex_wc/event_delivery_process.py` starts only after route and
claim authority exists. It enqueues and delivers `CLAIM_EXECUTION_HANDOFF`,
WorkResult, and approval events; it does not create a routing decision or a
Claim.

The only source-backed non-test caller that performs both route and claim is
the protected smoke harness. That proves the components but also confirms
that the installed product path is incomplete.

### 2.4 Existing Runtime Primitives Are Reusable

The shared runtime already provides:

- `SqlAlchemyJobQueue`, including idempotent enqueue by
  `(job_type, idempotency_key)`;
- `run_worker_once()` and `WorkerRunnerConfig`;
- `WorkerHeartbeatEmitter` and durable heartbeat storage;
- service logging, retry, dead-letter, package admission, readiness, and
  process shutdown patterns.

The WC event-delivery process is the closest process-composition reference.
The AE Agent Runtime dispatcher provides useful concurrency and lease design
evidence, but its executable-step joins, AE RuntimeJob leases, and capability
snapshot semantics are not the WC assignment data model and SHALL NOT be
copied as the implementation.

## 3. Reuse Decision

| Concern | Canonical owner/component | Decision |
|---|---|---|
| WorkItem state and version | WC coordination repository | Reuse |
| Candidate discovery | Existing AE Agent Registry candidate source | Reuse |
| Routing decision | Existing `RoutingPolicy` and `route()` | Reuse |
| Fresh claim authorization | Existing OA authorization source and `claim()` | Reuse |
| Assignment, Claim, handoff, outbox transaction | Existing WC repository | Reuse |
| Durable dispatch jobs | Shared `SqlAlchemyJobQueue` | Reuse |
| Job execution and retry | Shared `run_worker_once()` | Reuse |
| Liveness | Shared worker heartbeat | Reuse |
| Claim handoff to AE | Existing WC event-delivery worker | Reuse unchanged |
| AE RuntimeJob dispatcher | AE-specific runtime component | Do not reuse wholesale |
| Event-delivery job handler | Delivery-specific component | Keep separate |
| M1 Product Coordinator | Product preparation component | No dependency |

The reusable unit is the platform runtime library plus the WC owner service,
not one global platform JobQueue instance. The dispatcher uses the WC-local
`service_jobs` table and WC database transaction boundaries.

## 4. Normative Dispatch Contract

### 4.1 Process Identity

The installed process identity SHALL be:

```text
process_id: nex-wc-assignment-dispatcher
service_id: nex-wc
worker_type: wc.assignment.dispatch.worker
job_type: WC_ASSIGNMENT_DISPATCH
```

The process SHALL support the canonical installed profiles already used by
WC workers. It SHALL expose source check, dependency readiness, one-cycle
execution, bounded continuous execution, graceful stop, and package admission
using the same process contract style as `nex-wc-event-delivery-worker`.

### 4.2 Claimable Source States

The dispatcher SHALL discover only bounded rows in these states:

| Source state | Required action | Expected result |
|---|---|---|
| `CREATED` | call `WorkCoordinationService.route()` | `ROUTED`, or `CREATED` plus `NO_ELIGIBLE_AGENT` evidence |
| `ROUTED` | call `WorkCoordinationService.claim()` | `ASSIGNED` with active Claim and handoff outbox |
| `ASSIGNED` | no new transition | exact replay/no-op after authority verification |
| any other state | no dispatch | ignored or terminally classified |

Discovery SHALL return only identity and transition metadata: `tenant_id`,
`work_item_id`, current `state`, current `version`, and bounded scheduling
metadata. It SHALL NOT copy prompt text, business payloads, M1 values,
Project-specific logic, or private WorkItem content into the JobQueue payload.

### 4.3 Deterministic Job Identity

Each stage SHALL have a deterministic idempotency identity derived from:

```text
WC_ASSIGNMENT_DISPATCH
+ tenant_id
+ work_item_id
+ expected_version
+ action (ROUTE or CLAIM)
```

The job payload SHALL contain only the corresponding references and expected
version. `SqlAlchemyJobQueue.enqueue()` SHALL provide replay convergence for
the same job type and idempotency key. WC WorkItem version checks remain the
business authority when stale or concurrent jobs are observed.

The exact hash/UUID helper SHALL reuse an existing platform semantic or UUID
helper where compatible. A Slice-local digest implementation is prohibited.

### 4.4 Route Execution

For a `ROUTE` job the handler SHALL:

1. reload the WorkItem from WC authority;
2. return exact replay success if it has already advanced beyond the expected
   `CREATED` version through the same authoritative route;
3. otherwise require the exact `CREATED` state and expected version;
4. call `WorkCoordinationService.route()`;
5. treat `NO_ELIGIBLE_AGENT` as an observable retryable result with bounded
   backoff, not as successful completion, because the WorkItem remains
   `CREATED` at the same version;
6. use the shared dead-letter replay lineage when retry exhaustion requires
   an operator-authorized later attempt; and
7. allow the next bounded discovery cycle to enqueue the versioned `CLAIM`
   stage after a successful route.

The dispatcher SHALL NOT choose an agent itself.

### 4.5 Claim Execution

For a `CLAIM` job the handler SHALL:

1. reload the WorkItem and latest routing decision;
2. return exact replay success only when the existing Assignment, active
   Claim, generation, and handoff authority match the routed target;
3. otherwise require the exact `ROUTED` state and expected version;
4. call `WorkCoordinationService.claim()`;
5. rely on that method for fresh AE candidate and OA `work:claim`
   revalidation; and
6. leave the resulting handoff in the existing WC outbox.

The existing event-delivery worker SHALL remain the only installed process
that transports the claim handoff to AE. The assignment dispatcher SHALL not
call the AE handoff endpoint directly.

## 5. State, Retry, And Failure Semantics

### 5.1 Fail-Closed Classification

The following conditions SHALL produce no fabricated route, Claim,
Assignment, or handoff:

- AE Agent Registry unavailable;
- no eligible or active candidate;
- ambiguous or invalid routing target;
- OA unavailable, inactive, denied, or missing `work:claim` authority;
- cross-tenant or cross-Project candidate mismatch;
- stale WorkItem version;
- malformed routing decision;
- expired or superseded Claim; and
- unsupported WorkItem state.

Retryability SHALL follow existing typed WC errors. Authorization denial and
malformed authority are non-retryable for the current job identity. Temporary
Registry, OA, database, and transport failures are retryable under the shared
JobQueue policy.

`NO_ELIGIBLE_AGENT` is also retryable with bounded backoff. It SHALL remain
visible as routing evidence and worker telemetry. Exhaustion SHALL create a
dead-lettered job rather than mark the WorkItem complete; a later attempt
requires the existing operator-authorized replay contract with explicit
lineage and a new replay idempotency key. Continuous scans SHALL NOT create an
unbounded stream of replacement jobs for the same exhausted identity.

### 5.2 Crash And Replay Matrix

| Interruption point | Required recovery |
|---|---|
| before route mutation | same deterministic ROUTE job may retry |
| after route commit, before job ACK | replay observes `ROUTED`; no duplicate decision |
| between route and claim | restart discovers `ROUTED` and enqueues CLAIM |
| after claim commit, before job ACK | replay observes exact active authority; no duplicate Claim/outbox |
| after handoff outbox commit, before delivery | existing event-delivery worker resumes delivery |
| after delivery, before delivery ACK | existing delivery idempotency converges |

No runner may repair these states by manually updating WC tables.

### 5.3 Concurrent Dispatchers

Two or more dispatcher instances may discover the same WorkItem. Correctness
SHALL be provided by both layers:

1. deterministic JobQueue enqueue prevents duplicate active job identity;
2. WC expected-version and transactional repository checks prevent duplicate
   business transitions.

PostgreSQL concurrency evidence is mandatory. SQLite-only evidence is not
sufficient for this boundary.

## 6. Persistence And Migration Boundary

The first implementation SHALL reuse `wc_work_item`, `wc_routing_decision`,
`wc_assignment`, `wc_claim`, `wc_event_outbox`, `service_jobs`, and
`service_worker_heartbeats`.

No new business table is authorized. A bounded repository query for claimable
WorkItems may be added to the existing coordination repository.

Implementation stopped after actual `nex_wc_test` EXPLAIN evidence showed
that the tenant-leading legacy index could not serve the generic cross-tenant
scan without a sequential scan and sort. The approved corrective migration
adds only this partial index:

```text
ix_wc_work_item_dispatch_scan
  (state, created_at, tenant_id, work_item_id)
  WHERE state IN ('CREATED', 'ROUTED')
```

The migration adds no table or business field. Further schema changes remain
unauthorized without another source-backed stop and decision.

## 7. Installed Topology And Security

### 7.1 Composition

```text
AE public delegation
  -> WC WorkItem CREATED
  -> WC assignment dispatcher: ROUTE
  -> WC assignment dispatcher: CLAIM
  -> WC claim handoff outbox
  -> existing WC event-delivery worker
  -> AE claimed-work admission and Product routing
```

The assignment dispatcher and event-delivery worker remain separate
processes because they own different transitions and failure domains.

### 7.2 Dependency Readiness

Readiness SHALL fail closed unless all required dependencies are admitted:

- WC database identity and migration head;
- claimable WorkItem repository;
- WC-local JobQueue and worker heartbeat store;
- AE Agent Registry endpoint and signed service trust;
- OA authorization endpoint and signed service trust;
- routing policy configuration; and
- package/source admission.

Readiness SHALL not require a generation, embedding, or reranking provider.

### 7.3 Packaging And Deployment

The process SHALL be promoted through:

- Python package/console entrypoint or canonical `python -m` entrypoint;
- owner-scoped OCI image content and non-root execution;
- `--check` package and dependency probes;
- canonical Docker Compose service;
- bounded restart policy and stop grace period;
- environment inventory and secret-reference validation; and
- current-platform topology manifest.

No environment variable may contain an M1 ID, tenant-specific route,
Project list, fixed agent ID, or fallback candidate.

## 8. Prohibited Implementations And Residue Guard

The implementation and tests SHALL reject active product code containing:

- M1 or Golden-scenario dispatch branches;
- hard-coded tenant, company, Project, requester, agent, WorkItem, or Claim
  identifiers;
- fixed Project count or business amount;
- dictionary-based tenant routing;
- fallback agent selection when Registry/OA is unavailable;
- direct AE/WC/OA database cross-service reads;
- direct table updates by smoke runners;
- fixture-owned route or claim transitions;
- a second WC routing policy or authorization source;
- claim handoff HTTP delivery from the assignment dispatcher; or
- a new queue/worker framework when the shared runtime is sufficient.

Fixtures may seed prerequisite authority before a test. They may not execute
the transition being accepted.

## 9. Implementation Slices

### 9.1 CP-M1-E2E-FX-01B.6B.5B.1: Claimable Source And Dispatch Contract

- add bounded coordination-repository discovery for `CREATED` and `ROUTED`;
- freeze job type, payload, action, and deterministic identity;
- define stale, terminal, retryable, and non-retryable classifications;
- add and verify the approved partial dispatch-scan index migration.

### 9.2 CP-M1-E2E-FX-01B.6B.5B.2: Generic Scheduler And Handler

- enqueue route/claim jobs through `SqlAlchemyJobQueue`;
- execute jobs through `run_worker_once()`;
- call only existing `WorkCoordinationService.route()/claim()` for authority;
- prove exact replay, stale version, denial, and zero-mutation behavior.

### 9.3 CP-M1-E2E-FX-01B.6B.5B.3: Installed Process And Liveness

- add source check, readiness, one-cycle and continuous run modes;
- add heartbeat, service log, signal, shutdown, and restart behavior;
- compose existing AE Registry and OA authorization clients;
- prove crash-between-route-and-claim recovery.

### 9.4 CP-M1-E2E-FX-01B.6B.5B.4: Compose, OCI, And Topology Promotion

- add canonical process manifest and deployment environment inventory;
- add Docker Compose service and owner-scoped OCI entrypoint/check;
- verify non-root execution, health/readiness, start order, and rollback;
- add active-residue guard for demo, fixture, and M1-specific bindings.

### 9.5 CP-M1-E2E-FX-01B.6B.5B.5: Protected PostgreSQL Gate And Resume Decision

- run actual WC, OA, and AE PostgreSQL route/claim/handoff acceptance;
- prove concurrent dispatcher convergence, replay, restart, dependency denial,
  heartbeat, and zero residue;
- prove the existing event-delivery worker sends the authoritative handoff to
  AE exactly once at the business boundary;
- run focused Slice Gate and required repository regression;
- record the evidence and decide whether `.01B.7` may resume.

## 10. Verification Matrix

| Layer | Mandatory evidence |
|---|---|
| Unit | discovery bounds, job identity, payload validation, error classification |
| WC regression | route, claim, Assignment, Claim, outbox, exact replay |
| Shared runtime | JobQueue idempotency, retry/dead-letter, worker heartbeat |
| Concurrency | two dispatchers against actual `nex_wc_test` |
| Security | AE Registry and OA denial/unavailable/cross-scope cases |
| Restart | crash after route and crash after claim |
| Delivery | existing WC event-delivery worker sends claim handoff to AE |
| Installed | Compose, OCI, non-root, source/package/dependency checks |
| PostgreSQL | actual WC/OA/AE test databases, current migrations, zero residue |
| Coverage | current owner-service statement and branch gates maintained |

Remote generation-provider evidence is explicitly out of scope. It belongs
to the resumed public Product acceptance in `.01B.7` after this installed
dispatch boundary is closed.

## 11. Stop Conditions

Implementation SHALL stop and report before proceeding if:

1. route or claim authority must be duplicated outside
   `WorkCoordinationService`;
2. a protected runner would need to call route or claim to make the product
   path pass;
3. a new WC business table or unreviewed migration appears necessary;
4. installed Registry or OA contracts cannot express the required decision;
5. exact replay would create another Assignment, Claim, or handoff outbox;
6. concurrency safety cannot be demonstrated on PostgreSQL;
7. event-delivery must be merged into the assignment dispatcher;
8. any M1, tenant, Project, or fixture branch is required; or
9. process readiness would report READY without WC, Registry, OA, JobQueue,
   and heartbeat admission.

## 12. Closure And Resume Rule

`CP-M1-E2E-FX-01B.6B.5B` closes only when all five implementation Slices and
the protected installed Gate pass. Closure evidence SHALL demonstrate that a
publicly created generic WorkItem advances from `CREATED` through `ROUTED` to
an authoritative Claim without runner-owned transitions, and that the
existing WC event-delivery worker transports the resulting handoff to AE.

Only then may `CP-M1-E2E-FX-01B.7` resume its live-provider, Playwright, and
repository acceptance. The resumed Slice SHALL consume this installed
process; it SHALL not call route or claim directly.
