
# NeX Platform v1.0 As-Built Architecture Extraction Report v1.0

**Phase:** P1 — NeX Platform v1.0 As-Built Architecture Extraction  
**Baseline:** `nurigitdev/2607_nex_platform` tag `v1.0`  
**Commit:** `ab7af0fc3b42225d1d71d20d517889d694a01c03`  
**Method:** Source-first reconstruction from repository structure, service code, OpenAPI, DB migrations, deployment manifests, testing/quality documents  
**Important:** This report intentionally does **not** compare v1.0 against NeX Platform v2.1 / Agent v2.1 / NSL v0.2. That comparison begins in later phases.

---

## 1. Executive Summary

NeX Platform v1.0 is not a single-process RAG application. The implemented baseline is a **monorepo-style, separately owned, multi-service Enterprise AI/RAG platform** with:

- five backend APIs: `nex-oa`, `nex-ag`, `nex-ae-api`, `nex-cx`, `nex-mo`
- one user web application: `nex-ae-web`
- five service-owned PostgreSQL databases
- a shared runtime layer for JobQueue, worker execution, retry/dead-letter, operational events, structured logs, worker heartbeat, deployment and trust utilities
- five background workers and two daemons
- Traefik ingress/TLS boundary and OpenBao secret/trust integration
- private object-storage boundaries and remote model-provider integration
- formal OpenAPI contracts and service-owned migrations
- broad automated regression, PostgreSQL smoke, contract, security, Playwright, fault/recovery, deployment and release-readiness evidence

The primary business capability is still Enterprise RAG / grounded generation, but `nex-ae-api` already contains a **bounded early Agent/orchestration implementation** with intent/mode selection, retrieval orchestration, asynchronous generation, cancellation, retry, recovery, citation-quality handling, workspace/chat persistence and artifact/result lifecycle.

This makes v1.0 a meaningful implementation foundation for the later Agent Runtime transition rather than a disposable prototype.

---

## 2. Repository and Workspace Structure

Canonical top-level structure at tag `v1.0`:

```text
apps/
  nex-ae-web/

services/
  nex-oa/
  nex-ag/
  nex-ae-api/
  nex-cx/
  nex-mo/
  _shared/

contracts/
  openapi/
  schemas/
  examples/
  tests/

database/
  nex-oa/
  nex-ag/
  nex-ae-api/
  nex-cx/
  nex-mo/

deployment/
  compose/
  environments/
  model-serving/
  object-storage/
  postgres/
  security/
  ...

providers/
scripts/
tests/
docs/
```

The repository explicitly states that each backend service owns its own:

- Python package
- public service boundary
- database
- migrations

The `_shared` package provides runtime infrastructure only and is explicitly prohibited from absorbing service-private domain ownership.

---

## 3. Runtime Topology

### 3.1 Core processes

The local platform runner starts:

```text
5 backend APIs
+ 1 AE Web
+ 5 workers
+ 2 daemons
```

Backend APIs:

| Service | Port | Main role |
|---|---:|---|
| `nex-oa` | 8101 | Identity, authentication, authorization and service trust |
| `nex-ag` | 8102 | Admin, governance, audit and operator operations |
| `nex-ae-api` | 8103 | User-facing orchestration, workspace/chat/result/artifact facade |
| `nex-cx` | 8104 | Content intelligence, ingestion, retrieval and grounded generation execution |
| `nex-mo` | 8105 | Model/provider abstraction, execution and runtime operations |
| `nex-ae-web` | 5173 | User-facing web workspace |

Background process manifest:

```text
nex-ae-artifact-render-worker
nex-ae-retention-daemon

nex-ag-remediation-sync-worker
nex-ag-dispatch-daemon

nex-cx-async-generation-worker
nex-cx-ingestion-worker
nex-cx-remediation-worker
```

### 3.2 Runtime dependency graph

The implementation defines the API dependency order as:

```text
nex-oa
  ↑
  ├──────── nex-mo
  │           ↑
  ├──────── nex-cx ──────────┐
  │                           │
  ├──────── nex-ae-api ◄─────┘
  │
  └──────── nex-ag
             ├─ OA
             ├─ AE
             ├─ CX
             └─ MO

nex-ae-web
   ↓
nex-ae-api
```

More exactly:

- OA has no NeX service dependency.
- MO depends on OA.
- CX depends on OA + MO.
- AE-API depends on OA + CX.
- AG depends on OA + AE + CX + MO.
- AE-Web depends on AE-API.

This confirms that provider execution is not performed directly from AE.

---

## 4. Service Ownership / SoR Reconstruction

### 4.1 NeX-OA

As-Built responsibilities include:

- tenant and subject registry
- local user credential lifecycle
- login/session lifecycle
- service principals
- service credentials
- signed service tokens
- token exchange / introspection / revocation
- JWKS/signing-key lifecycle
- group/role authorization
- effective authorization resolution
- federated identity and OIDC-related integration
- security/audit events

Explicit design intent:

```text
OA = identity/auth/service trust authority
OA != retrieval owner
OA != provider/model owner
OA != chat/workspace owner
```

### 4.2 NeX-CX

As-Built responsibilities include:

- source file and logical content lifecycle
- ownership/ACL lineage
- extraction
- document intelligence
- chunking
- lexical/BM25 index
- embedding/vector index
- summaries + summary embeddings
- hybrid candidate generation / ranking / reranking
- retrieval policy and confidence calibration
- permission-aware retrieval
- retrieval package persistence/materialization
- grounded generation request validation
- provider-facing prompt composition
- CX generation execution record
- structured draft / citation validation
- async generation and recovery
- remediation execution
- pgvector/private vector boundaries
- ingestion/retrieval/generation workers

CX owns the evidence and document-grounded execution side, but not the final user chat/workspace response.

### 4.3 NeX-MO

As-Built responsibilities include:

- provider registry and aliases
- embedding execution
- reranking execution
- generation execution
- provider readiness / health
- provider retries and resilience
- provider telemetry
- model catalog lifecycle
- model rollout / activation / rollback
- capacity scheduling
- runtime observability
- DGX/vLLM integration boundary

Model access is by stable capability/alias; raw provider endpoints are intentionally kept private.

### 4.4 NeX-AE API

As-Built responsibilities include:

- user-facing API facade
- login/session facade integration with OA
- workspace state
- chat interaction state
- intent / execution-mode policy
- prompt/template/runtime policy
- retrieval orchestration toward CX
- generation orchestration toward CX
- async generation projection
- generation lifecycle, progress, cancel/retry/recovery
- generated response persistence and lineage
- citation-quality workflow
- user feedback
- repaired-response review/decision flow
- artifact handoff/render/storage/download lifecycle
- upload handoff and document facade
- analytics and recommendation surfaces

This service is the location of the v1.0 **bounded early Agent/orchestrator**.

### 4.5 NeX-AG

As-Built responsibilities include:

- operational/readiness projections
- cross-service trace aggregation
- generation audit
- retrieval operations views
- audit evidence/integrity/retention
- operator review cases
- remediation tasks and execution dispatch
- worker/job visibility and control dispatch
- log/event projections
- alerting / SLO / notification views
- artifact operations projection
- read-mostly cross-service operations

AG does not become the owner of other service data. Where PostgreSQL projections are enabled, the implementation wraps other service stores as read-only.

### 4.6 NeX-AE Web

As-Built role:

- Korean-default browser workspace
- login/session UX
- upload/document UX
- chat UX
- generation progress/recovery UX
- artifact preview/download/lifecycle UX

It is not a business-data or model-provider authority.

---

## 5. Public API Surface

OpenAPI endpoint counts at tag `v1.0`:

| Service | Contracted operations |
|---|---:|
| AE API | 71 |
| CX | 62 |
| MO | 34 |
| OA | 32 |
| AG | 96 |
| **Total** | **295** |

Notable AE API surfaces include:

- workspace create/read/activity
- upload and upload progress
- document library/detail/search
- retrieval context create/read
- chat create/read/refresh
- asynchronous response/progress
- cancel/retry/recovery
- citation-quality view
- repaired response review/decision
- feedback
- artifact links
- artifact rendering / download
- runtime policy
- prompt/analytics surfaces

Notable CX surfaces include:

- document upload and processing
- extraction/chunk/embedding/lexical/summary stages
- vector-index readiness/reconciliation
- retrieval context
- async generation jobs
- grounded generation
- structured drafts and generation events
- remediation execution
- worker/reconciliation/job control

This API surface confirms that the implementation is materially beyond a minimal upload/search/chat prototype.

---

## 6. Database and Persistence Architecture

### 6.1 Service-owned databases

The canonical DB rule is:

```text
Each service owns its database and migrations.
Cross-service foreign keys/joins are intentionally avoided.
Cross-service references travel through API/contract identity.
```

Service DB environments:

```text
NEX_OA_DATABASE_URL
NEX_AG_DATABASE_URL
NEX_AE_DATABASE_URL
NEX_CX_DATABASE_URL
NEX_MO_DATABASE_URL
```

Canonical schema is PostgreSQL. SQLite is used for selected repository-level regression compatibility, not as the authoritative production schema.

### 6.2 Migration inventory

At `v1.0`:

| Service | Migration files |
|---|---:|
| AE API | 25 |
| CX | 23 |
| MO | 10 |
| OA | 18 |
| AG | 20 |
| **Total** | **96** |

### 6.3 Common persistence foundations

Each service database can contain common operational structures such as:

```text
service_jobs
service_operational_events
service_log_entries
service_worker_heartbeats
job replay lineage
```

The shared runtime supplies SQLAlchemy adapters while preserving service-local ownership.

### 6.4 Job queue behavior

Implemented JobQueue characteristics include:

- service-local queues
- idempotency support
- worker claim
- PostgreSQL `FOR UPDATE SKIP LOCKED`
- retry decision
- bounded exponential backoff using `available_at`
- dead-letter representation
- cancel / retry / replay controls
- replay creates a new queued job instead of mutating the failed source job

---

## 7. RAG / Document Intelligence Pipeline

The implemented v1.0 processing flow can be reconstructed as:

```text
Browser / AE
     ↓
CX document upload
     ↓
Source byte storage
     ↓
Extraction
     ↓
Normalized text / document intelligence
     ↓
Chunking
     ├──────────────┐
     ↓              ↓
Lexical/BM25     Embedding / pgvector
     └──────┬───────┘
            ↓
Hybrid candidate generation
            ↓
Ranking / optional reranking via MO
            ↓
Permission filtering
            ↓
Retrieval quality / confidence policy
            ↓
Retrieval Context Package
            ↓
AE orchestration / generation policy
            ↓
CX grounded generation boundary
            ↓
MO generation provider
            ↓
CX generation record + evidence/citations
            ↓
AE final response / artifact
```

Additional implemented features include:

- no-answer and low-confidence branches
- stale-index/readiness handling
- retrieval package hashing/materialization
- source anchors and evidence metadata
- summary generation + summary embeddings
- owner-scoped summary similarity
- citation repair / grounded-output validation
- retrieval score calibration and threshold decisions

---

## 8. v1.0 Early Agent / Chat Orchestration — P1 Finding

P1 does not yet perform the dedicated Agent analysis; however the As-Built extraction establishes the following facts.

The implementation documentation explicitly defines the v1.0 AE agent as:

```text
bounded orchestrator
not unconstrained autonomous worker
```

Supported execution modes include:

```text
GROUNDED_ANSWER
DOCUMENT_SUMMARY
DOCUMENT_GENERATION
```

The orchestration loop includes:

```text
user request
→ workspace/owner validation
→ intent or explicit mode
→ retrieval planning
→ CX retrieval context
→ generation policy/template/output contract
→ CX grounded generation
→ MO provider execution
→ final AE result
→ optional artifact
```

Actual `chat.py` additionally implements:

- persistent/in-memory chat stores
- owner-scoped visibility
- workspace chat binding
- idempotent chat records
- synchronous and asynchronous generation clients
- refresh
- progress
- cancel
- retry
- recovery
- citation-quality workflow
- repaired-response handoff/review/decision
- artifact links
- generated-response lineage

**P1 conclusion:** v1.0 already contains a meaningful early Agent lifecycle and orchestration layer.  
The exact reuse/refactor mapping is intentionally deferred to **P2**.

---

## 9. Shared Runtime / Reliability Foundation

The shared runtime contains infrastructure for:

- app/service shell
- auth and service tokens
- database pools
- common persistence
- JobQueue
- job control
- worker runner
- worker heartbeats
- operational events
- structured service logs
- cross-service traces
- recovery helpers
- process manifests and runtime topology
- OpenBao secret resolution
- object storage lifecycle
- PostgreSQL backup/restore/PITR/recovery
- release candidate / production admission
- staging and fault/load/soak support

This is infrastructural runtime only; service-private domain ownership remains outside `_shared`.

---

## 10. Security and Trust Model

Implemented security architecture includes:

```text
Browser/User
   ↓
OA login/session
   ↓
AE facade
   ↓
OA-backed user/owner context

Service-to-service
   ↓
OA service principal / signed token
   ↓
audience/scoped service admission
```

Deployment-side trust includes:

- OpenBao for secret references
- TLS certificate/trust references
- service-specific DB secret references
- service-to-service token references
- provider API key references
- object-storage credential references

The deployment manifests avoid embedding raw provider/DB credentials in the service configuration.

---

## 11. Model Operations As-Built

MO is not a thin LLM wrapper.

The implemented service covers:

- embedding API
- rerank API
- generation API
- provider aliases/routes/profiles
- readiness and health
- provider telemetry
- model runtime observability
- catalog lifecycle
- alias activation / rollback
- model rollout state/events
- capacity scheduling and rollout controls

Document-grounded generation reaches MO through CX, not directly from AE in the canonical v1.0 path.

---

## 12. Governance / Operations As-Built

AG already provides an extensive operator surface including:

- service readiness
- generation audit
- quality disposition
- remediation task lifecycle
- audit evidence/integrity/retention
- operator review cases
- escalation and dispatch
- worker liveness
- job control
- event and log search
- cross-service trace
- retrieval-package and calibration projections
- SLO/alert/notification surfaces
- artifact operations projections

AG's cross-service DB mode is designed as read-only projection, preserving service SoR.

---

## 13. Deployment Architecture

The supported v1.0 staging/production-style single-host topology contains:

```text
Traefik
OpenBao

nex-oa
nex-ag
nex-ae-api
nex-cx
nex-mo
nex-ae-web

5 service-owned PostgreSQL databases
private/object-storage boundary
3 remote model-provider capabilities
```

Production release documentation explicitly distinguishes:

```text
implementation/release-readiness completion
!= production deployment authorization
```

The v1.0 tag is therefore valid as an As-Built implementation baseline even though the recorded protected release decision at closure is `NO_GO`.

Distributed features such as multi-host service failover, PostgreSQL automatic failover, storage quorum and GPU autoscaling/failover remain explicit backlog rather than being falsely claimed as v1.0 capabilities.

---

## 14. Quality / Test Architecture

The development process requires regression for every source-code Slice.

Quality levels:

```text
Slice Gate
Checkpoint Gate
Full Gate
```

Checkpoint/Slice coverage threshold recorded in the repository:

```text
Statement coverage: 95%
Branch coverage:    94%
```

The test inventory covers areas including:

- unit/domain behavior
- contract/API drift
- database/migration drift
- PostgreSQL smoke
- JobQueue/retry/replay
- worker lifecycle
- ingestion and retrieval
- async generation
- cancel/retry/recovery
- citation quality and repair
- artifact lifecycle
- auth/security
- cross-service trust
- AG governance and operator review
- Playwright browser flows
- deployment/restart/rollback
- preproduction faults/load/soak
- production readiness and release evidence

The strategy is mock-first; live DGX/vLLM evidence is treated as protected additional evidence, not as a substitute for deterministic regression.

---

## 15. P1 As-Built Architecture Diagram

```text
                         ┌────────────────────┐
                         │    Company User    │
                         └─────────┬──────────┘
                                   │
                          ┌────────▼────────┐
                          │   NeX-AE Web    │
                          └────────┬────────┘
                                   │
                          ┌────────▼────────┐
                          │   NeX-AE API    │
                          │ Workspace/Chat  │
                          │ Early Agent     │
                          │ Result/Artifact │
                          └───┬─────────┬───┘
                              │         │
                       auth   │         │ retrieval/generation
                              │         │
                     ┌────────▼───┐  ┌──▼───────────────────┐
                     │   NeX-OA   │  │       NeX-CX         │
                     │ Identity   │  │ Content/Ingestion     │
                     │ Auth/AuthZ │  │ BM25 + Vector         │
                     │ Trust      │  │ Retrieval/Evidence    │
                     └────────────┘  │ Grounded Generation  │
                                     └──────────┬────────────┘
                                                │ provider alias
                                     ┌──────────▼────────────┐
                                     │       NeX-MO          │
                                     │ Model/Provider Ops    │
                                     │ Embed/Rerank/Generate │
                                     └───────────────────────┘

                 ┌───────────────────────────────────────────┐
                 │                  NeX-AG                   │
                 │ Governance / Audit / Ops / Review / Trace│
                 │ read-only projections + controlled ops   │
                 └───────────────────────────────────────────┘

 Cross-cutting:
 ─ service-owned PostgreSQL DB x5
 ─ shared JobQueue / Worker / Retry / Events / Logs / Heartbeats
 ─ Traefik / OpenBao / private object storage
 ─ deterministic tests + PostgreSQL smoke + Playwright + release evidence
```

---

## 16. P1 Findings — Without v2.1 Comparison

The following statements are supported by the v1.0 repository itself:

1. v1.0 is a **multi-service platform**, not a monolithic RAG application.
2. RAG/content intelligence remains the primary end-user capability.
3. AE already implements a bounded early Agent/orchestration model.
4. Asynchronous lifecycle handling is already significant: progress, cancel, retry and recovery exist.
5. Service ownership and DB boundaries are intentionally strong.
6. Shared runtime infrastructure already provides several primitives useful for later execution-runtime evolution.
7. OA and AG are materially implemented, not placeholder service names.
8. Model operations are centralized in MO.
9. CX is both retrieval/evidence authority and the default document-grounded generation execution mediator.
10. Production-readiness engineering is unusually extensive for a v1.0 Enterprise RAG release.

---

## 17. Items Explicitly Deferred to Later Phases

P1 does **not** decide:

- whether v1.0 ChatInteraction maps to AgentExecution
- which v1.0 runtime/job identities should be reused
- which Agent code is REUSE / REFACTOR / REPLACE
- how NSL v0.1 maps to NSL v0.2
- how Agent v2.1 differs from the v1.0 bounded agent
- how WC / CA / PA / EA should be integrated
- whether any v2.1 Frozen architecture concept is missing or incorrect

Those decisions belong to P2+.

---

## 18. P1 Exit Gate

### Gate checklist

- [x] Repository baseline pinned to tag `v1.0`
- [x] Top-level repository layout reconstructed
- [x] Five service ownership boundaries identified
- [x] Web boundary identified
- [x] API dependency graph reconstructed
- [x] API contract surface inventoried
- [x] Database ownership and migration model reconstructed
- [x] Core RAG/document-intelligence path reconstructed
- [x] Early AE Agent/chat existence and scope identified
- [x] Shared queue/worker/reliability runtime identified
- [x] Deployment topology reconstructed
- [x] Security/trust model identified
- [x] Testing/quality structure identified
- [x] No v2.1 comparison performed prematurely

## P1 Status

> **P1 — NeX Platform v1.0 As-Built Architecture Extraction: CLOSED**

---

## 19. Next Phase

Proceed to:

> **P2 — Existing `nex-ae-api` Early Agent Detailed Analysis**

P2 should focus on:

```text
ChatInteraction identity
Workspace binding
intent / execution-mode selection
retrieval planning
generation lifecycle
async generation
JobQueue relationship
cancel / retry / recovery
response/result lineage
artifact linkage
current state machine
persistent entities
service calls
failure semantics
```

The objective is to establish the exact starting point for later Agent Runtime refactoring without yet integrating NSL v0.2.
