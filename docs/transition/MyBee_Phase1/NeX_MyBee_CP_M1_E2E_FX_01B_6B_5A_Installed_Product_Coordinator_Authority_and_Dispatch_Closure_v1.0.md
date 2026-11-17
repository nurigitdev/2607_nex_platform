# NeX MyBee CP-M1-E2E-FX-01B.6B.5A: Installed Product Coordinator Authority and Dispatch Closure v1.0

## 1. Status And Authority

- Decision date: 2026-11-18
- Status: DESIGN_CLOSED_IMPLEMENTATION_REQUIRED
- Repository: nurigitdev/2607_nex_platform
- Branch: codex/mybee-phase1-implementation
- Source-backed review commit: 772e418b
- Parent amendment:
  `NeX_MyBee_CP_M1_E2E_FX_01B_6B_Installed_M1_Preparation_and_Deterministic_Plan_Activation_Closure_v1.0.md`
- Predecessor: CP-M1-E2E-FX-01B.6B.4
- Suspended Slice: CP-M1-E2E-FX-01B.6B.5
- Successors after closure:
  - CP-M1-E2E-FX-01B.6B.5 completion
  - CP-M1-E2E-FX-01B.7 resume decision
- Runtime code changes by this document: none
- Database migration authorized by this document: none by default
- Remote model-provider dependency: none for focused 6B.5A implementation

This controlled amendment closes the structural gaps discovered while
entering installed composition. It does not add an M1 scenario path. It
productizes three reusable platform boundaries:

1. owner-authoritative Product Preparation resolution;
2. step-less Product Coordinator dispatch through the existing Agent Runtime;
3. capability-selected Product Coordinator activation from a public request.

M1 is the first admitted consumer of these boundaries. No generic runtime
component may contain an M1 business-value branch, and future product
coordinators must be installable without creating another queue, worker, or
scenario runner.

## 2. Source-Backed Entry Findings

### 2.1 Registration Is Not Activation

The Product Coordinator registry and M1 registration are immutable and
hash-bound, but the M1 registration remains `CONTRACT_ONLY`. The canonical
installed AE API and worker processes do not own an active coordinator
composition or expose its readiness.

Consequently, component-level calls prove the coordinator contract but do not
prove that a public WorkIntent can enter it.

### 2.2 Product Authority Reload Is Not Installed

`InstalledM1ProductPlanningCoordinator` requires an
`M1PreparationAuthoritySource`. The repository currently defines the protocol
and uses test-owned sources, but has no installed source that reconstructs the
same authority after restart from EOS and OA.

Existing protected APIs expose useful fragments, including Project
resolution, Project authorization, LegalEntity binding, semantic account
resolution, and approval evidence. They do not currently expose one exact,
hash-bound Product Preparation authority projection covering:

- tenant and requester identity;
- company selector resolution and functional currency;
- the exact Project set and fresh OA authorization decisions;
- debit and credit semantic-account resolution;
- business and accounting approval policy revisions; and
- an authority effective timestamp and semantic hash.

AE cannot reconstruct missing authority by reading EOS/OA databases, trusting
model output, or accepting fixed environment values.

### 2.3 Product Resume Jobs Cannot Be Claimed

The shared wait/event/runtime-job mechanics correctly create a step-less
`RESUME_EXECUTION` job for `PRODUCT_COORDINATOR`. The malformed-job
reconciler preserves that job. However, runnable discovery and
capability-aware claim still require an inner join to
`ae_executable_step`. A valid Product Coordinator job therefore remains
queued forever.

Adding `PRODUCT_COORDINATOR` to the executable-step registry would be a false
model: Product Preparation is a pre-plan runtime handler, not an ExecutablePlan
step or NSL executor.

### 2.4 Public Planning Bypasses Product Coordination

The installed WC claim handoff currently invokes semantic candidate admission
and provider plan compilation directly. It has no capability-selected product
router. The provider plan is useful planning evidence, but cannot become
financial authority or bypass proposal, human approval, VoucherCandidate,
posting admission, and `READY_FOR_D04` preparation.

### 2.5 Installed Process Readiness Is Incomplete

The canonical AE worker process composes executable-step dispatch, execution,
result closure, and product Skill runtime. It does not compose:

- the active Product Coordinator registry;
- installed Product authority sources;
- Product Preparation checkpoint and generalized wait/event repositories;
- Product resume route handlers;
- READY-state plan activation; or
- coordinator dependency and rollback readiness.

This is an installed composition gap, not evidence that the earlier durable
components should be reimplemented.

## 3. Normative Product Architecture

### 3.1 Product Coordinator Is A Platform Extension Point

The platform SHALL define Product Coordinator installation independently of
M1. One installed registration binds:

- exact capability ID, version, and registration hash;
- coordinator ID, version, implementation identity, and activation state;
- authority resolver identity and response contract;
- checkpoint schema and replay policy;
- materializer identity;
- required Skill bundle locks; and
- supported runtime assignment kinds.

Selection SHALL use exact WorkIntent capability identity and the immutable
Product Capability Registry. Selection SHALL NOT use scenario names, prompt
substring checks, tenant dictionaries, model-selected implementation names,
or fixed business values.

The first active registration is MyBee M1. The generic product router and
worker know only the Product Coordinator contract and registration identity.

### 3.2 Owner-Authoritative Resolution Boundary

EOS SHALL own a protected, read-only Product Preparation authority resolution
contract because EOS owns the business identities and accounting policies
that form the transaction authority. The canonical operation identity is:

```text
FINANCE.TRANSACTION_PREPARATION_AUTHORITY.RESOLVE
```

The HTTP route may use `POST` because the selector is structured and bounded,
but it remains a zero-mutation query. The request SHALL contain only:

- tenant and authenticated requester lineage;
- business-context hash;
- company selector;
- requested Project Codes;
- amount, currency, and recognition date;
- registered debit and credit semantic keys; and
- capability/coordinator release identity.

The semantic account keys come from the admitted Product registration, not
from a model, runner, tenant-specific environment variable, or fixture.

EOS SHALL resolve its own LegalEntity, Project, account, period, and approval
policy authority through existing repositories and services. Fresh Project
authorization SHALL be obtained through the existing OA protected decision
contract. Direct AE reads of EOS or OA persistence are prohibited.

The successful response SHALL be an exact, bounded, hash-bound authority
projection sufficient to construct `M1PreparationAuthority`. It SHALL include
source revisions and evidence hashes for every mutable authority. It SHALL
exclude raw prompts, approval bodies, credentials, and private unrelated
records.

Missing, ambiguous, stale, revoked, cross-tenant, cross-company, inactive, or
semantically inconsistent authority fails closed with zero mutation. The same
resolution is executed at begin and every approval resume boundary.

### 3.3 Generic Runtime Assignment Kinds

The installed Agent Runtime SHALL distinguish runtime assignment kind from
step executor kind.

The initial admitted assignment kinds are:

```text
EXECUTABLE_STEP
PRODUCT_COORDINATOR
```

`EXECUTABLE_STEP` preserves the existing executor-kind and backend-profile
selection. `PRODUCT_COORDINATOR` is derived from the persisted
WaitRegistration, typed Product binding, and RuntimeJob lineage. It has no
ExecutableStep and cannot be registered as `LOCAL_SKILL` or another step
executor.

Runnable discovery and claim SHALL consider both assignment kinds in one
fairness, lease, retry, heartbeat, attempt, and shutdown lifecycle. The
existing `ae_runtime_job`, `ae_runtime_job_attempt`, wait, event, and dispatch
lease structures remain authoritative. No second Product queue or worker is
allowed.

The generic assignment handler registry SHALL route:

- `EXECUTABLE_STEP` to the existing step execution handler;
- `PRODUCT_COORDINATOR` to the installed Product Coordinator handler.

The Product handler SHALL resolve its route from persisted authority, resolve
the exact active coordinator registration, reload WorkIntent, AgentContext,
capability snapshot, AgentExecution, checkpoint, event, and fresh owner
authority, and then call the coordinator. When the resulting checkpoint is
the exact registered ready state, it invokes existing plan activation and the
existing scheduler.

### 3.4 Public Product Planning Router

The public WC claim-handoff path SHALL invoke a generic Product Planning
Router before ordinary provider-plan compilation.

The router SHALL:

1. load the durable WorkIntent and capability snapshot;
2. resolve an exact active Product Coordinator registration;
3. retain provider context, intent, and plan candidates as non-authoritative
   evidence where applicable;
4. invoke the registered coordinator begin handler;
5. return a bounded common planning-admission projection; and
6. leave non-product capabilities on the existing semantic planning path.

The router cannot contain an M1 conditional. M1 behavior is supplied by the
registered implementation and authority resolver.

Provider PLAN output cannot be persisted as the authoritative financial plan.
The deterministic D12/D04 AgentPlan remains materialized only from
`READY_FOR_D04` authority.

### 3.5 One Installed Composition Factory

AE API admission and the AE worker process SHALL obtain Product Coordinator
components from one canonical installed composition factory. The factory
binds:

- Product Capability and Product Coordinator registries;
- Product authority resolver registrations;
- existing transaction-preparation adapters;
- checkpoint and generalized wait/event repositories;
- resume route source and assignment handler registry;
- existing AgentPlan, PlanValidation, ExecutablePlan, AgentExecution, and
  RuntimeJob repositories;
- existing materializers and scheduler; and
- readiness and rollback projections.

The API process uses the composition for public begin admission and event
intake. The worker uses the same registration and source identities for
resume and plan activation. Duplicate assembly logic and process-local
registration drift are prohibited.

## 4. Activation, Readiness, And Rollback

### 4.1 Activation Lock

`CONTRACT_ONLY` may advance to `ACTIVE` only through an immutable installed
activation lock. The lock SHALL bind:

- Product Coordinator registry hash;
- exact coordinator registration hash;
- Product Capability Registry hash;
- authority resolver contract and implementation identity;
- required Skill bundle locks;
- runtime assignment handler set;
- checkpoint schema and migration inventory; and
- rollback receipt.

Changing any bound identity makes readiness fail closed.

### 4.2 Installed Readiness

Staging and production readiness SHALL fail unless all of the following are
true:

- Product package and capability locks are admitted;
- every `ACTIVE` coordinator has exactly one installed implementation;
- every implementation has one admitted authority resolver;
- EOS and OA endpoints and service tokens are configured;
- required AE migrations are current;
- Product checkpoint, wait, event, job, plan, and dispatch tables exist;
- both runtime assignment kinds have handlers;
- product resume jobs are discoverable and claimable; and
- rollback metadata is valid.

Readiness output contains identities, hashes, and status only. It does not
expose tokens, business input, approval content, or private evidence.

### 4.3 Rollback

Rollback changes the Product Coordinator activation lock from `ACTIVE` to
`CONTRACT_ONLY` and restarts the canonical AE API and worker processes.
Already persisted checkpoints, waits, events, and jobs remain durable.

While the coordinator is not active:

- new matching public requests fail closed before business mutation;
- valid Product resume jobs remain queued and observable;
- no job is reclassified as malformed or dead-lettered solely because the
  Product handler is unavailable; and
- reactivation with the exact admitted lock resumes from durable authority.

Rollback SHALL NOT delete or rewrite Product Preparation history.

## 5. Configuration And Deployment Boundary

Compose and OCI configuration may provide only deployment facts:

- EOS and OA base URLs;
- bounded HTTP timeouts;
- service-token bootstrap references;
- Product registry, activation-lock, Skill-lock, and package paths;
- worker identity and generic assignment capabilities; and
- ordinary database and process settings.

Configuration SHALL NOT contain tenant, company, Project, amount, currency,
account, approval policy, ratio, evidence, candidate, or Plan defaults.

The canonical process remains `nex_ae_api.agent_runtime_process`. No M1
process, demo process, scenario process, or extra daemon is introduced.

## 6. Persistence And Migration Decision

No new database migration is authorized by default.

The implementation SHALL derive Product assignment identity from existing
RuntimeJob, WaitRegistration, typed binding, and route-source data. Existing
Product Preparation checkpoint and binding structures remain authoritative.

Implementation stops for an explicit persistence decision if correct,
concurrent claim semantics cannot be achieved without adding an assignment
kind column or changing a durable constraint. It must not hide such a need in
JSON payloads or infer the assignment from untrusted content.

## 7. Required Implementation Slices

### CP-M1-E2E-FX-01B.6B.5A.1: Canonical Product Authority Resolution Contract

- define the protected EOS request/response schemas and operation identity;
- compose existing EOS authority and fresh OA decisions without direct
  cross-service database access;
- implement the installed AE authority-source client and exact response
  validation;
- prove multiple tenants, companies, Project counts, currencies, dates,
  account semantics, and policy revisions; and
- prove ambiguity, revocation, drift, and cross-scope zero mutation.

### CP-M1-E2E-FX-01B.6B.5A.2: Generic Runtime Assignment And Dispatch

- generalize runnable discovery and claim across executable-step and Product
  Coordinator assignments;
- preserve the existing queue, lease, attempt, fairness, retry, and heartbeat
  lifecycle;
- install the generic resume-target handler registry;
- keep valid unhandled Product jobs queued and observable; and
- prove no Product or M1 branch enters the generic step executor registry.

### CP-M1-E2E-FX-01B.6B.5A.3: Public Product Router And Installed Composition

- add capability-selected Product routing to the public claim-handoff path;
- assemble API and worker components through one installed factory;
- connect begin, approval resume, READY activation, existing plan stores, and
  existing scheduler;
- retain provider planning artifacts as non-authoritative evidence; and
- prove ordinary non-product planning remains compatible.

### CP-M1-E2E-FX-01B.6B.5A.4: Activation Lock, Compose, OCI, And Readiness

- create immutable coordinator activation and rollback receipts;
- promote M1 from `CONTRACT_ONLY` only after dependency admission;
- bind canonical Compose/OCI environment and process checks;
- add deployment and product-source residue guards; and
- prove fail-closed startup for missing or drifted dependencies.

### CP-M1-E2E-FX-01B.6B.5A.5: Protected Product Gate And Resume Decision

- run actual AE, EOS, OA, and WC PostgreSQL protected integration;
- prove a public-originated request reaches both approval waits,
  `READY_FOR_D04`, deterministic plan persistence, and scheduler ownership;
- prove exact replay, restart, ACK loss, rollback, and reactivation;
- run the required Checkpoint Gate and zero-residue checks;
- record source, deployment, fixture-residue, and migration evidence; and
- admit or deny completion of 6B.5 and resumption of 01B.7.

Remote generation, embedding, and reranker providers are not required for
6B.5A. The resumed 01B.7 acceptance owns live Qwen3.5-9B and authenticated
Playwright evidence.

## 8. Verification Matrix

The protected Gate SHALL prove at least:

```text
exact capability selects installed Product Coordinator       = PASS
non-product capability preserves existing planning path       = PASS
authority resolution comes only from EOS/OA                   = PASS
fresh authority reload after process restart                  = PASS
ambiguous/revoked/cross-scope authority                        = DENIED
step-less Product RuntimeJob discoverable and claimable        = PASS
Product job uses existing lease/attempt/retry lifecycle        = PASS
Product job never masquerades as ExecutableStep/LOCAL_SKILL    = PASS
public WorkIntent reaches durable first preparation wait       = PASS
both approval resumes use persisted route and fresh authority  = PASS
READY_FOR_D04 activates existing deterministic materializer    = PASS
AgentPlan/Validation/ExecutablePlan exact replay               = PASS
existing scheduler owns first D12/D04 RuntimeJob               = PASS
provider PLAN retained only as non-authoritative evidence      = PASS
rollback leaves durable Product jobs queued                    = PASS
reactivation resumes without duplicate mutation                = PASS
fixed business values in source/config/runner                  = 0
Product-specific queue/worker/daemon                           = 0
unauthorized database migration                                = 0
cross-service private repository or SQL access                 = 0
zero residue after protected smoke                             = PASS
```

Required regression includes AE runtime dispatch/worker/resume, P5/P6/P7
planning compatibility, Product Preparation, EOS authority and accounting,
OA Project authorization, WC approval delivery, D12/D04 Skill runtime,
result publication, and canonical deployment checks.

## 9. Anti-Fixture And Productization Rules

The following shortcuts are prohibited:

- an M1 or scenario-name conditional in generic planning, dispatch, worker,
  scheduler, compiler, or result code;
- a fixed tenant, company, requester, Project, amount, currency, account,
  policy, ratio, candidate, evidence, or Plan identity;
- a test source, seed file, environment variable, or runner as live business
  authority;
- direct SQL or private repository access across service ownership;
- a second Product queue, worker, resume daemon, or installed runtime;
- treating provider PLAN output or an event ACK as approval authority;
- invoking a private coordinator or mutating runtime state from Playwright or
  a smoke runner; or
- activating the coordinator without an immutable activation and rollback
  receipt.

Business seed data may prepare authoritative test databases before a request.
Runtime code may access it only through the same protected owner-service APIs
used by an installed deployment.

## 10. Stop Conditions

Implementation stops for an explicit decision if:

1. EOS/OA cannot produce the exact authority without a new authoritative
   contract or ambiguous policy selection;
2. generic Product assignment claim requires a new durable column or weakens
   executable-step claim safety;
3. public routing cannot preserve provider evidence without making it
   financial authority;
4. API and worker processes cannot share exact registration and source
   identities;
5. Product activation requires fixed M1 business values;
6. rollback would lose, rewrite, dead-letter, or duplicate durable work;
7. a migration becomes necessary; or
8. the public journey still requires runner state injection or a private
   component call.

Any stop report must name the exact source constraint, violated invariant,
smallest correction, migration impact, and affected regression matrix.

## 11. Closure And 01B.7 Resume Rule

6B.5A closes only when the generic installed Product Coordinator boundary is
active and a public-originated M1 WorkIntent reaches existing scheduler
ownership through owner-authoritative preparation, shared runtime dispatch,
and deterministic plan activation without fixture-driven state.

Closure evidence must include actual PostgreSQL, installed Compose/OCI
readiness, exact replay/restart/rollback, anti-fixture residue, coverage, and
zero-residue results.

Only then may 6B.5 be marked complete and CP-M1-E2E-FX-01B.7 resume. 01B.7
remains responsible for live provider evidence, authenticated Playwright, the
complete public M1 journey, Repository Full Gate, and final closure. It may
not compensate for or bypass any 6B.5A product boundary.
