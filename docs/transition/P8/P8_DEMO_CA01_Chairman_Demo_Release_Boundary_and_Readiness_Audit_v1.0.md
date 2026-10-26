# P8-DEMO-CA01 Chairman Demo Release Boundary and Readiness Audit v1.0

**Status:** SOURCE-BACKED AUDIT COMPLETE / DEMO IMPLEMENTATION ENTRY AUTHORIZED WITH BLOCKING GATES

**Business Baseline:** P8 Final As-Built v1.2 / P8-S113

**Baseline Branch:** `transition/p4-agent-runtime-foundation`

**Baseline Commit:** `df4d9bb0`

**Demo Branch:** `codex/p8-chairman-demo-release`

**Date:** 2026-10-25

## 1. Purpose

P8 v1.2 proves the governed NVTProject, Project membership, approval,
controlled WRITE, Voucher, exact replay, and authenticated Web journeys against
actual PostgreSQL databases, live generation, and Chromium. That evidence is a
valid implementation baseline; it is not yet a reproducible installed Demo
Release.

The existing single-host Docker Compose and OCI release set were frozen before
NeX-WC and NeX-EOS entered the platform. This audit defines the minimum release
boundary required to demonstrate the P8 v1.2 capability from an installed
single-host environment without rewriting the P8 business contracts.

The intended Chairman journey is:

```text
start an installed NeX Platform release
-> register a small organization and employees
-> create an NVTProject and Project
-> add several Project members in one request
-> sign in through AE Web
-> enter a natural-language Voucher request
-> complete the required approval
-> commit and verify the Voucher in EOS
-> retrieve the authoritative result
```

## 2. Executive Decision

The Demo Release SHALL be developed on the dedicated branch:

```text
codex/p8-chairman-demo-release
```

The branch starts at `df4d9bb0`, the commit that closes P8-S113. Historical
S143 through S146 Compose evidence and P8 v1.0 through v1.2 As-Built records
remain immutable.

Demo work is an additive deployment and operations closure. It SHALL NOT
become a second implementation of OA, AE, WC, EOS, NSL, approval, Project, or
Voucher business behavior.

The current source is **not yet Demo Release ready**. WC/EOS packaging,
cross-service configuration, background execution, installation, and installed
golden-journey gates are blocking work.

## 3. Audited Sources

The audit covered these authoritative source groups:

| Area | Source |
| --- | --- |
| P8 implementation baseline | `P8_Final_AsBuilt_Baseline_and_P9_Handoff_v1.2.md` |
| Service identities and ports | `services/_shared/nex_runtime/app.py` |
| Database ownership | `services/_shared/nex_runtime/database.py` |
| Local runtime topology | `scripts/dev/run_all_services.py`, `scripts/dev/run_service.py` |
| OCI artifact set | `services/_shared/nex_runtime/deployment_artifacts.py` |
| OCI build automation | `scripts/deployment/build_platform_images.py` |
| Single-host Compose | `deployment/compose/s143-staging.compose.yaml` |
| Object storage overlay | `deployment/compose/s146-object-storage.override.yaml` |
| TLS routes | `deployment/compose/traefik/dynamic.yaml` |
| Protected Compose acceptance | `scripts/smoke/run_s143_external_staging_acceptance.py` |
| AE runtime execution | `agent_runtime_worker.py`, `agent_runtime_dispatcher.py` |
| WC integration | `services/nex-wc/nex_wc/main.py` |
| EOS integration | `services/nex-eos/nex_eos/app.py`, `dependencies.py` |
| P8 protected rehearsal | `scripts/smoke/run_p8_s112_nvt_membership_acceptance.py` |

## 4. Verified Current State

### 4.1 P8 business capability is closed

P8 v1.2 already verifies:

```text
OA current identity and authority
AE natural-language candidate admission
WC approval
NSL controlled WRITE
EOS NVTProject / Project / membership / Voucher mutation
live Qwen3.5-4B generation
authenticated AE Web Chromium journey
exact replay and zero backend residue
```

These contracts are reused unchanged by the Demo Release.

### 4.2 The source runtime knows WC and EOS

`SERVICE_SPECS`, database configuration, and local development launchers know
seven backend services on ports `8101` through `8107`:

```text
nex-oa       8101
nex-ag       8102
nex-ae-api   8103
nex-cx       8104
nex-mo       8105
nex-wc       8106
nex-eos      8107
```

AE Web remains the eighth application artifact. WC and EOS have FastAPI
applications, PostgreSQL migrations, service-token boundaries, and protected
P8 smoke coverage.

### 4.3 The installed release topology is still the older six-image set

The OCI catalog currently contains only:

```text
nex-oa-runtime
nex-ae-runtime
nex-cx-runtime
nex-mo-runtime
nex-ag-runtime
nex-ae-web
```

The S143 Compose file starts five Python APIs and AE Web. It has no WC or EOS
container, image input, database reference, OpenBao role, health check, service
DNS name, or Traefik route.

The S143 protected acceptance similarly expects five database URLs and five
Python runtime images. Passing S143 therefore does not prove the P8 v1.2
runtime.

### 4.4 P6-P8 asynchronous execution is not in the packaged process set

The packaged background process catalog predates P6. It includes AE artifact
render/retention, AG operations, and CX workers, but not the AE Agent Runtime
dispatcher or executable worker introduced by P6.

The AE worker module has configuration, readiness, bounded execution, signal
handling, and a `--check` command. Its module-level execution command still
fails closed when the composed LOCAL_SKILL execution handler is unavailable.
The dispatcher provides durable dispatch rounds but is not admitted as a
long-running packaged process.

P8 protected tests compose these objects inside their controlled runners. That
proves semantics but not an independently running installed topology.

### 4.5 Existing development databases are clean but not migration-current

A read-only PostgreSQL inspection on 2026-10-25 confirmed that all seven
development databases exist and are owned by the expected service roles:

| Service | Database / role | Applied / source migrations | Business tables | Exact business rows |
| --- | --- | ---: | ---: | ---: |
| `nex-oa` | `nex_oa_dev` / `nex_oa_user` | `0 / 18` | 0 | 0 |
| `nex-ag` | `nex_ag_dev` / `nex_ag_user` | `0 / 20` | 0 | 0 |
| `nex-ae-api` | `nex_ae_dev` / `nex_ae_user` | `0 / 60` | 0 | 0 |
| `nex-cx` | `nex_cx_dev` / `nex_cx_user` | `0 / 23` | 0 | 0 |
| `nex-mo` | `nex_mo_dev` / `nex_mo_user` | `0 / 10` | 0 | 0 |
| `nex-wc` | `nex_wc_dev` / `nex_wc_user` | `0 / 13` | 0 | 0 |
| `nex-eos` | `nex_eos_dev` / `nex_eos_user` | `8 / 15` | 12 | 0 |

The first six databases have no `schema_migrations` table. EOS is an older,
empty P8 schema missing migrations `2508` through `2514`. No database contains
an extra migration version.

The canonical migration runner already defines all seven `NEX_*_DATABASE_URL`
bindings as its `dev` profile. Normal service runtime does not require a
`*_test` or `*_demo` suffix. Test target resolvers and destructive test reset
helpers, by contrast, require the exact `*_test` database and role identities.
Consequently, the existing development databases can be admitted for this
Demo Release after migration and isolation controls; no source-level database
rename is required.

## 5. Audit Findings

| ID | Severity | Finding | Required closure |
| --- | --- | --- | --- |
| `DEMO-01` | BLOCKER | OCI release set has six artifacts and excludes WC/EOS. | Admit eight immutable application images and refresh build provenance. |
| `DEMO-02` | BLOCKER | Compose has no WC/EOS service, health, network, TLS route, or dependency wiring. | Add a Demo-specific Compose overlay and Traefik dynamic configuration. |
| `DEMO-03` | BLOCKER | OpenBao and environment references omit WC/EOS databases, AppRoles, and AE/WC/EOS trust tokens. | Add owner-scoped secrets and prove fail-closed startup and rotation. |
| `DEMO-04` | BLOCKER | The installed topology has no admitted AE Agent Runtime dispatcher/executable worker lifecycle. | Package and run the exact P6-P8 execution composition with readiness and restart recovery. |
| `DEMO-05` | BLOCKER | Existing S143 acceptance proves only the pre-WC/EOS topology. | Add an eight-application protected installation and restart gate. |
| `DEMO-06` | HIGH | Seven clean development databases exist but are not migration-current or operationally reserved for Demo use. | Admit the exact seven `*_dev` identities, apply current migrations, freeze concurrent use, and add a tenant-scoped idempotent fixture lifecycle. |
| `DEMO-07` | HIGH | WC delivery and EOS outbox components exist as source adapters but their installed process ownership is not frozen. | Record whether each is synchronous or background in the golden journey and admit every required consumer. |
| `DEMO-08` | HIGH | EOS intentionally does not expose the shared JobQueue/service-log operation surface. | Use EOS API/readiness and business-specific evidence; do not falsely report EOS as AG-managed until separately implemented. |
| `DEMO-09` | HIGH | No single install/start/stop/restart/rehearsal runbook covers the P8 topology. | Produce operator commands, recovery steps, preflight, and evidence collection. |
| `DEMO-10` | MEDIUM | Historical Compose uses `restart: "no"` for bounded staging acceptance. | Define explicit Demo lifecycle policy without mutating historical S143 evidence. |

No finding authorizes weakening tenant isolation, current OA authority, approval
domain separation, controlled WRITE, idempotency, reconciliation, or
verification.

## 6. Frozen Demo Release Decisions

### 6.1 Additive deployment profile

The Demo Release SHALL layer new files over the attested S143/S146 files. It
SHALL NOT edit the historical files merely to make a new acceptance pass.

The expected shape is:

```text
s143-staging.compose.yaml
+ s146-object-storage.override.yaml
+ P8 Demo application/topology overlay
+ P8 Demo Traefik dynamic configuration
```

The runtime profile remains `staging_live`. A new global `demo_live` profile is
not introduced solely for Compose naming.

### 6.2 Eight-image application release set

The complete application release set SHALL contain:

```text
nex-oa-runtime
nex-ag-runtime
nex-ae-runtime
nex-cx-runtime
nex-mo-runtime
nex-wc-runtime
nex-eos-runtime
nex-ae-web
```

Worker and daemon containers reuse the immutable image owned by their service.
They do not create additional application image identities.

A release set is admitted only when all eight images are built from one clean
source revision and have image ID, manifest/config digest, base digest,
source/lock digest, non-root user, and packaged entrypoint evidence.

### 6.3 Single-host infrastructure boundary

The Demo Release uses:

```text
Docker Compose on one host
Traefik for TLS ingress
OpenBao for owner-scoped secrets and PKI
RustFS for private Voucher evidence objects
external PostgreSQL databases on the Demo host
DGX remote generation / embedding / reranking providers
```

Kubernetes, HA PostgreSQL, a service mesh, registry push, and distributed
failover remain out of scope.

### 6.4 Admitted development databases as isolated Demo state

The release SHALL NOT use `*_test` databases as its durable demonstration
state. For the current single-host Chairman demonstration, the existing clean
development databases are the admitted targets:

```text
nex_oa_dev   owned by nex_oa_user
nex_ag_dev   owned by nex_ag_user
nex_ae_dev   owned by nex_ae_user
nex_cx_dev   owned by nex_cx_user
nex_mo_dev   owned by nex_mo_user
nex_wc_dev   owned by nex_wc_user
nex_eos_dev  owned by nex_eos_user
```

This decision is safe because the inspected databases contain zero business
rows and are not targeted by exact-name test reset helpers. It is conditional
on all of the following:

1. Demo preparation applies the current source migration inventory with the
   canonical `dev` migration profile.
2. The seven databases are reserved for the Demo branch until the Chairman
   demonstration closes; other branches and manual development do not write
   to them.
3. OpenBao supplies only the normal `NEX_*_DATABASE_URL` runtime variables.
   No `NEX_*_TEST_DATABASE_URL` is injected into Demo containers.
4. Pre-rehearsal backup and migration evidence record all seven exact database
   and role identities.
5. Seed and cleanup operate only on the dedicated Demo tenant. Test reset
   functions and whole-database truncation are forbidden.

Separate `*_demo` databases become mandatory when development and demonstration
must run concurrently, when the release moves to another host, or when multiple
independent Demo datasets are required. They are not required for the current
single-host, serialized preparation period.

The seed/reset command may affect only the dedicated Demo tenant and must fail
closed without an exact confirmation value.

### 6.5 Required process inventory

The installed release always starts the seven backend APIs and AE Web. Before
the topology is admitted, a source-backed process matrix SHALL decide and test
all consumers required by the public golden journey, including at minimum:

```text
AE Agent Runtime dispatcher
AE Agent Runtime executable worker
WC claim/work-result/approval event delivery where asynchronous
EOS outbox publication where asynchronous
```

An in-test function call is not an installed process. A process is admitted
only with a packaged command, owner image, non-root execution, database pool,
health or heartbeat evidence, SIGTERM behavior, and restart-safe recovery.

### 6.6 External provider policy

Generation is required for the natural-language Voucher journey. Embedding and
reranking are required only when the selected rehearsal includes RAG. Provider
preflight records alias, model revision, dtype/readiness, and calibration
identity without recording API keys or raw prompts.

The release fails closed before the demonstration when a required provider is
unavailable. It does not silently switch the Chairman journey to a mock.

### 6.7 Demo data lifecycle

Seed data SHALL be deterministic and idempotent:

```text
one Demo tenant
one Chairman/operator account and required approver accounts
one small organization and leadership ladder
bounded active employee set
one NVTProject and one Project
one account/policy fixture sufficient for Voucher approval
```

Repeated setup returns the same stable business references or performs an
explicit versioned update. It does not create duplicate employees, projects,
memberships, accounts, or approval policies.

Teardown is tenant-scoped. Rehearsal state may be preserved intentionally, but
that choice must be explicit; a failed run must never trigger a global test DB
reset.

## 7. Target Demo Topology

```text
Browser
  -> Traefik TLS
     -> AE Web
     -> AE API
        -> OA      identity, login, current authority
        -> MO      generation and provider routing
        -> WC      NSL_WRITE / BUSINESS_FORMAL approval
        -> EOS     NVTProject, Project, membership, Voucher
        -> CX      existing Chat/RAG path when selected

AE Agent Runtime dispatcher + worker
  -> AE PostgreSQL runtime jobs, checkpoints, evidence
  -> NSL v0.2.1 admitted wheel and exact Skill artifacts
  -> WC approval and EOS controlled WRITE adapters

RustFS
  -> AE-private Voucher evidence objects

OpenBao
  -> seven backend owner identities, database secrets, trust tokens, TLS
```

Only Traefik exposes the Web/API ingress. OpenBao administrative access remains
loopback-bound. PostgreSQL and RustFS are not public browser endpoints.

## 8. Acceptance Gates

### 8.1 Static and packaging gate

```text
eight-image catalog complete
all required process bindings complete
dependency lock and NSL v0.2.1 wheel admission pass
Compose config renders with no placeholder or raw secret
Traefik routes resolve to declared services
all images run as non-root with read-only roots where supported
```

### 8.2 Database and secret gate

```text
seven Demo database URLs target the admitted exact *_dev databases and roles
all service migrations are current
OpenBao paths and AppRoles are owner-scoped
AE/WC/EOS signed service-token audiences and scopes are exact
missing or stale secret causes fail-closed startup
```

### 8.3 Lifecycle gate

```text
clean install
ordered startup
all required readiness/heartbeat checks pass
graceful stop
restart with existing durable state
worker lease/checkpoint recovery
no duplicate business mutation after restart
```

### 8.4 Protected Chairman golden journey

The final protected run SHALL use actual Demo PostgreSQL databases, RustFS,
OpenBao/Traefik, live generation, and authenticated Chromium. It SHALL prove:

```text
login
organization and employee fixture visibility
NVTProject and Project create/list/update
multi-member add with deterministic partial result
natural-language Voucher candidate and plan
approval inbox and decision
EOS commit, verification, and query
exact replay without duplicate mutation
browser result presentation
service restart and authoritative result recovery
```

Mocks remain valid for unit regression. They do not satisfy the protected Demo
Release gate.

### 8.5 Evidence gate

Reports contain commit/tree, image digests, Compose digest, migration heads,
provider model identities, gate results, and redacted timing summaries. They
must not contain passwords, API keys, tokens, raw prompts, employee private
data, Voucher contents, or attachment bytes.

## 9. Recommended Follow-on Sequence

Each item remains an independent implementation, test, commit, and push unit:

| Order | Work item | Primary outcome |
| ---: | --- | --- |
| 1 | Demo runtime/process closure | Executable AE dispatcher/worker and exact required delivery consumers |
| 2 | Eight-image OCI catalog closure | WC/EOS images, process bindings, complete provenance |
| 3 | Demo Compose/trust closure | WC/EOS services, routes, OpenBao ownership, signed trust |
| 4 | Demo database and fixture closure | Seven `_dev` admissions/migrations, guarded idempotent seed/reset |
| 5 | Installed lifecycle closure | Build, install, start, stop, restart, health and recovery |
| 6 | Protected Chairman rehearsal | Live generation, PostgreSQL, RustFS, Playwright golden journey |
| 7 | Demo release and operations closure | Runbooks, evidence pack, immutable release identifier |

The exact Slice identifiers SHALL be frozen before implementation. This audit
does not combine those units into one unreviewable change.

## 10. Exit Criteria

P8-DEMO work may close only when:

1. The eight-image release set is complete and provenance-admitted.
2. Every public journey dependency runs as an installed process.
3. WC/EOS database, secret, route, trust, and health boundaries are present.
4. The seven admitted `_dev` databases are migration-current, reserved for
   Demo use, and have repeatable guarded fixtures.
5. Start, stop, restart, and durable recovery pass on the single host.
6. The complete protected Chairman journey passes without mock fallback.
7. Exact replay produces no duplicate Voucher or membership mutation.
8. Evidence is redacted and the operator runbooks are executable.
9. Repository regression and coverage remain at or above the canonical gate.
10. Historical P8 and S143-S146 evidence remains unchanged.

## 11. Final Audit Decision

```text
P8 v1.2 BUSINESS BASELINE ACCEPTED
DEDICATED DEMO BRANCH ESTABLISHED
HISTORICAL DEPLOYMENT EVIDENCE PRESERVED
SIX-IMAGE INSTALLED TOPOLOGY NOT SUFFICIENT
WC/EOS PACKAGING AND COMPOSE INTEGRATION REQUIRED
AE AGENT RUNTIME INSTALLED PROCESS CLOSURE REQUIRED
SEVEN CLEAN DEV DATABASES CONDITIONALLY ADMITTED FOR DEMO
MIGRATION / RESERVATION / TENANT-GUARD CLOSURE REQUIRED
PROTECTED INSTALLED GOLDEN JOURNEY REQUIRED
DEMO IMPLEMENTATION ENTRY AUTHORIZED WITH BLOCKING GATES
```
