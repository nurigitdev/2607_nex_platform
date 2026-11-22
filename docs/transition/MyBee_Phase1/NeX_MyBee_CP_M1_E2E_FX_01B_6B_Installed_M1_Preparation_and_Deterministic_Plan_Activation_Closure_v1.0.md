# NeX MyBee CP-M1-E2E-FX-01B.6B: Installed M1 Preparation and Deterministic Plan Activation Closure v1.0

## 1. Status And Authority

- Decision date: 2026-11-17
- Status: DESIGN_CLOSED_IMPLEMENTATION_REQUIRED
- Repository: nurigitdev/2607_nex_platform
- Reviewed branch: codex/mybee-phase1-implementation
- Reviewed source commit: 98ab7dd1
- Parent packet:
  NeX_MyBee_CP_M1_E2E_FX_01B_Durable_Business_Context_and_M1_Transaction_Orchestration_Closure_v1.0.md
- Predecessors:
  - CP-M1-E2E-FX-01B.4
  - CP-M1-E2E-FX-01B.5 and 5A
  - CP-M1-E2E-FX-01B.6 and 6A
- Successor after closure: CP-M1-E2E-FX-01B.7
- Runtime code changes by this document: none
- Database migration authorized by this document: none by default
- Remote model-provider dependency for focused 6B implementation: none
- Remote model-provider dependency after closure: required by 01B.7

This controlled amendment closes the installed-runtime gap found immediately
before CP-M1-E2E-FX-01B.7. The component contracts needed to prepare the M1
transaction, materialize a deterministic D12/D04 plan, execute that plan, and
integrate its financial result exist. They are not yet connected as one
restart-safe product path originating from the admitted M1 WorkIntent.

This amendment does not create an M1 scenario runner, a test-only execution
path, or a second Agent Runtime. It requires a reusable product-planning
coordination boundary selected by admitted capability metadata. M1 is the
first registered product coordinator, not a special branch embedded in the
generic semantic-admission or worker code.

## 2. Source-Backed Entry Finding

The repository currently contains these valid foundations:

| Foundation | Current product authority | Confirmed state |
| --- | --- | --- |
| WorkIntent and business context | AE WorkIntent, AgentContext, and typed/hash-bound business context | persisted and propagated |
| Live semantic evidence | context, intent, and plan candidates | persisted as non-authoritative evidence |
| Background planning | BackgroundAgentPlanningService and DeterministicCandidateAdmissionService | directly admits and compiles the provider AgentPlan |
| M1 preparation | InstalledM1TransactionPreparation and M1TransactionPreparationAdapter | composed for readiness; no installed product caller drives its three stages |
| Preparation states | WAITING_BUSINESS_APPROVAL, WAITING_ACCOUNTING_APPROVAL, READY_FOR_D04 | deterministic component contract exists |
| M1 materialization | M1InstalledSkillRuntime.materialize_transaction_plan | implemented and tested; no product path invokes it at READY_FOR_D04 |
| Plan persistence | existing AgentPlan, PlanValidation, ExecutablePlan repositories | implemented and immutable |
| Scheduling | existing SqlAlchemyMultiStepEngine and scheduler composition | implemented |
| Financial result integration | M1FinancialResultIntegrator and 01B.6 product components | implemented after D04 result |

The installed path therefore stops before authoritative transaction
preparation:

~~~text
IA public prompt
  -> live context, intent, and PLAN evidence
  -> WorkIntent and AgentContext
  -> provider AgentPlan admitted and compiled directly
  -> [M1 preparation is not activated]
  -> [READY_FOR_D04 is not reached]
  -> [the 01B.5 materializer is not called]
  -> [D12/D04 scheduling cannot start from the public product path]
~~~

Component tests that call the preparation adapter or materializer directly
prove those components, but do not prove the installed product journey.
CP-M1-E2E-FX-01B.7 cannot fill this gap in its smoke runner. The gap must be
closed in product code first.

## 3. Normative Product Decision

### 3.1 Capability-Selected Product Coordinator

AE SHALL introduce a product-planning coordinator contract and an immutable
registration boundary. The registration is resolved from admitted product
capability identity and version, not from prompt text, tenant-specific
dictionaries, scenario names, or fixed business values.

The generic contract SHALL support at least these operations:

1. begin preparation from an admitted WorkIntent and AgentContext;
2. resume preparation from an authoritative approval reference;
3. expose a canonical, hash-bound preparation checkpoint;
4. report whether deterministic plan materialization is allowed; and
5. materialize a canonical AgentPlan only after the registered product
   coordinator reaches its admitted ready state.

The first registration is the MyBee M1 coordinator. Future product journeys
may register their own coordinator without adding branches to:

- generic semantic candidate admission;
- BackgroundAgentPlanningService;
- the Agent Runtime worker;
- the scheduler;
- the deterministic compiler; or
- the NSL runtime.

### 3.2 Provider Evidence Is Advisory, Not Financial Authority

Live provider INTENT and PLAN output remains mandatory semantic evidence for
01B.7, but cannot:

- approve a business proposal;
- approve accounting review;
- create an EOS VoucherCandidate by itself;
- choose an approved Allocation Plan;
- authorize posting;
- supply a financial evidence ID;
- replace OA, WC, or EOS authority; or
- become the executable D12/D04 plan before READY_FOR_D04.

The provider PLAN may select or recommend an admitted product capability and
may be retained in planner provenance. The final executable business plan is
materialized deterministically from the exact WorkIntent, AgentContext,
capability release, owner-service authority, and READY_FOR_D04 checkpoint.

### 3.3 Installed Product Flow

After closure, the canonical flow is:

~~~text
authenticated IA prompt
  -> live context, intent, and plan candidate evidence
  -> typed/hash-bound M1 WorkIntent and AgentContext
  -> immutable capability release resolution
  -> registered product coordinator
  -> begin_proposal()
  -> WAITING_BUSINESS_APPROVAL
  -> owner-service approved document evidence
  -> continue_after_business_approval()
  -> VoucherCandidate create, validate, and review submission
  -> WAITING_ACCOUNTING_APPROVAL
  -> fresh accounting approval and posting admission evidence
  -> continue_after_accounting_approval()
  -> READY_FOR_D04
  -> existing 01B.5 materialize_transaction_plan()
  -> AgentPlan save
  -> PlanValidation save and runtime apply
  -> ExecutablePlan save
  -> existing scheduler schedule_next()
  -> existing worker executes D12 and D04
  -> existing 01B.6 allocation, P&L, WA, WC, and IA result integration
~~~

## 4. Product Coordinator Contract

### 4.1 Registration Identity

Every coordinator registration SHALL be immutable and include:

- coordinator ID and version;
- supported product capability ID and release identity;
- implementation reference;
- admitted preparation adapter source identity;
- admitted materializer source identity;
- initial, waiting, ready, and terminal state vocabulary;
- required owner-service operations;
- supported executor kinds and Skill bundle locks;
- checkpoint schema version;
- replay policy; and
- semantic registration hash.

The product capability release and coordinator registration must be resolved
before preparation starts and must remain bound to the WorkIntent lineage.
An altered registration, capability release, adapter source identity, or
materializer identity is a conflict, not an upgrade-in-place.

### 4.2 Generic Coordinator Inputs

The generic coordinator receives only persisted, validated inputs:

- tenant ID and authenticated requester subject;
- AgentExecution, WorkIntent, and AgentContext identity and hashes;
- admitted capability snapshot and release identity;
- typed business request context and context hash;
- immutable provider semantic evidence references;
- authoritative owner-service references needed by the current transition;
- correlation, causation, and idempotency identity; and
- the preceding checkpoint, when resuming.

It cannot receive hidden defaults from a smoke runner or environment-specific
fixture. Product-specific interpretation remains in the registered product
coordinator and owner-service clients, not in generic runtime code.

### 4.3 M1 Coordinator Responsibilities

The M1 coordinator SHALL compose existing components rather than duplicate
their logic:

- InstalledM1TransactionPreparation;
- M1TransactionPreparationAdapter;
- the existing EOS Business Approval and VoucherCandidate clients;
- M1InstalledSkillRuntime.materialize_transaction_plan;
- existing AgentPlan, PlanValidation, and ExecutablePlan repositories;
- existing compiler and scheduler; and
- existing result integration from 01B.6.

The coordinator does not calculate accounts, FX, allocation ratios, approval
policy, posting proof, or Project P&L. Those values remain owned by EOS, OA,
WC, and their already admitted product contracts.

## 5. Durable Preparation And Resume Boundary

### 5.1 Existing Storage First

Implementation SHALL first prove whether the current AE persistence model can
represent preparation and resume semantics without changing their meaning.
The source audit must cover at least:

- WorkIntent and AgentContext immutable lineage;
- AgentExecution state and version;
- AgentPlan versioning for one execution;
- PlanValidation and ExecutablePlan ownership;
- runtime jobs and scheduler idempotency;
- wait registration semantics;
- external event inbox idempotency and ACK state;
- step result ownership; and
- existing private evidence references and hashes.

No new table is authorized by this document. A new migration is not the
default implementation plan.

### 5.2 Semantic Reuse Rule

Existing storage may be reused only when its schema and constraints preserve
the exact business meaning.

In particular:

- BUSINESS_FORMAL and accounting approval are not NSL_WRITE approval;
- business approval events are not WORK_RESULT events;
- a pre-plan preparation checkpoint is not automatically an executable-step
  result;
- an owner-service evidence reference is not a provider candidate reference;
  and
- an event-delivery ACK is not approval authority.

The implementation SHALL NOT relabel BUSINESS_FORMAL or accounting approval
as WORK_RESULT or NSL_APPROVAL merely to fit existing checks. It SHALL NOT
stuff the checkpoint into prompt text, goal text, error details, or unrelated
JSON metadata.

If the existing schema cannot represent the two approval waits and restart
cursor without semantic overloading, implementation stops for a narrowly
scoped persistence decision. That stop must include the exact violated
constraint and the smallest proposed migration. It must not silently add a
table or weaken an existing check.

### 5.3 Preparation Checkpoint

Every preparation transition produces a canonical checkpoint containing:

- schema and stage;
- tenant, requester, WorkIntent, AgentContext, and AgentExecution lineage;
- business context hash;
- capability release and coordinator registration identity;
- preparation adapter source identity;
- owner-service operation, case, work-item, document, candidate, review, and
  admission references applicable to the stage;
- preceding checkpoint hash;
- idempotency and correlation identity;
- checkpoint version; and
- semantic checkpoint hash.

Private business content remains in its existing owner and private storage
boundary. The coordinator persists references, bounded projections, and
hashes. Exact replay returns the same checkpoint identity and hash.

### 5.4 Approval Resume

An approval notification only wakes or makes the coordinator eligible to
resume. Before transition, the coordinator must query the authoritative
owner service and verify the exact immutable evidence.

For business approval, it verifies the approved document envelope and its
proof through the existing product API. For accounting approval, it verifies
the current VoucherCandidate review and posting admission through EOS.

The resume boundary SHALL reject:

- a foreign tenant or requester;
- a different WorkIntent or business context hash;
- a different approval case, candidate, or evidence identity;
- a stale, revoked, expired, returned, or rejected approval;
- out-of-order stage delivery;
- an event whose source authority cannot be reloaded; and
- an event that tries to skip a preparation stage.

Event delivery, replay, and ACK state must be idempotent. Lost ACK followed by
redelivery must return the same checkpoint and create no duplicate business
case, candidate, review, plan, or job.

## 6. READY_FOR_D04 Plan Activation

### 6.1 Exact Admission

The 01B.5 materializer may be called only when the persisted checkpoint is
exactly READY_FOR_D04 and all of these identities still match:

- tenant, requester, AgentExecution, WorkIntent, and AgentContext;
- business context hash;
- capability snapshot and release;
- coordinator and adapter source identity;
- VoucherCandidate identity, version, revision, and hash;
- accounting evidence and proof hash;
- posting admission identity, hash, and expiry;
- approved Allocation Plan authority from 01B.5A; and
- installed Skill bundle and operation locks.

Any drift fails closed before AgentPlan persistence.

### 6.2 Persistence Order

The coordinator SHALL use the existing repositories and their immutable
contracts. The admitted order is:

1. materialize and validate the canonical AgentPlan;
2. save or exact-replay the AgentPlan;
3. persist and apply the existing PlanValidation result;
4. compile and save or exact-replay the ExecutablePlan and steps;
5. commit the complete planning lineage;
6. invoke the existing scheduler; and
7. let the existing runtime worker claim and execute the first ready step.

The scheduler cannot run before the complete plan is durable. A crash after
any durable boundary must reload exact lineage and continue without creating
a second semantic plan or duplicate job.

### 6.3 Plan Version And Candidate Provenance

The source audit must prove how a provider plan candidate, a preparation
phase, and the final deterministic transaction plan coexist under the current
AgentExecution and plan-version rules.

The implementation may retain provider PLAN evidence as provenance, but it
must not persist that evidence as an executable financial AgentPlan if doing
so would block or ambiguously replace the final deterministic plan. Any
staged or bootstrap plan approach must use existing version and repository
semantics exactly.

If the current plan repository cannot admit the final deterministic plan for
the same execution without overwriting immutable history or inventing a
scenario-specific exception, implementation stops for an explicit design
decision.

## 7. Replay, Restart, And ACK-Loss Rules

The installed coordinator SHALL implement these invariants:

| Condition | Required result |
| --- | --- |
| same WorkIntent first delivery | one preparation lineage |
| same WorkIntent exact replay | same checkpoint and references |
| process restart at either wait | resume from durable checkpoint |
| business approval event redelivery | no duplicate proposal or VoucherCandidate |
| accounting approval event redelivery | no duplicate admission or plan |
| ACK lost after durable resume | event redelivery returns exact replay |
| crash after AgentPlan save | reload and finish validation/compile exactly once |
| crash after ExecutablePlan save | reload and schedule without duplicate plan |
| crash after schedule_next | existing scheduler/job idempotency converges |
| stale or out-of-order event | denied with zero mutation |
| changed business context | conflict with zero mutation |
| changed capability or registration | conflict with zero mutation |
| revoked or expired authority | denied with zero mutation |
| cross-tenant or cross-company probe | denied with zero disclosure |

The same business request cannot produce duplicate proposal cases,
VoucherCandidates, approval cases, posting admissions, AgentPlans,
ExecutablePlans, RuntimeJobs, Journals, AllocationBatches, P&L projections,
WA evidence, WorkResults, or IA publications.

## 8. Productization And Anti-Fixture Rules

The following are mandatory:

1. Product coordination is selected through the immutable capability
   registry, not a scenario-name conditional.
2. Tenant, company, requester, Project set, amount, currency, FX rate,
   accounts, dates, approval IDs, Plan IDs, allocation ratios, and evidence
   IDs come from persisted input or authoritative services.
3. The M1 composition layer is thin and invokes generalized product
   components.
4. Tests use multiple tenants, company selectors, Project counts, currencies,
   amounts, dates, account policies, and allocation ratios.
5. Business seed data may prepare authoritative databases before a request,
   but cannot be read by runtime code as a fixture.
6. Smoke and Playwright runners call public product APIs only and cannot
   mutate internal runtime state.
7. No demo, Golden A, M1 fixed-value, or test-only environment variable may
   control product behavior.
8. No direct SQL or private repository access is allowed across service
   ownership boundaries.

Residue scanning SHALL cover product source, deployment configuration,
entrypoints, environment names, and protected runners.

## 9. Implementation Slices

### CP-M1-E2E-FX-01B.6B.1: Product Coordinator Contract And Storage-Fit Audit

- define the generic product coordinator and immutable registration contract;
- register the M1 coordinator through admitted capability metadata;
- map the current WorkIntent, AgentExecution, plan, wait, event, and result
  storage constraints;
- prove whether existing storage can represent both approval waits and the
  final plan without semantic overloading;
- add anti-fixture and generic-runtime branch guards; and
- stop for a persistence decision if existing storage is not semantically
  sufficient.

### CP-M1-E2E-FX-01B.6B.2: Durable Preparation And Approval Resume

- connect the M1 WorkIntent to the registered product coordinator;
- activate the existing proposal and VoucherCandidate preparation adapter;
- persist hash-bound preparation checkpoints using the admitted existing
  storage design;
- resume only after fresh owner-service evidence verification;
- implement event replay, out-of-order rejection, and ACK-loss convergence;
  and
- run focused AE, WC, OA, and EOS regression.

### CP-M1-E2E-FX-01B.6B.3: Deterministic Plan Persistence And Scheduling

- invoke the existing 01B.5 materializer only at READY_FOR_D04;
- persist AgentPlan, PlanValidation, ExecutablePlan, and step lineage through
  existing repositories;
- preserve provider PLAN evidence without treating it as financial authority;
- start execution through the existing scheduler and worker composition;
- prove crash recovery at every persistence boundary; and
- add no M1 branch to generic compiler, scheduler, or worker code.

### CP-M1-E2E-FX-01B.6B.4: Replay, Restart, And ACK-Loss Protected Gate

- run actual AE, WC, OA, and EOS PostgreSQL migration/state smoke;
- prove proposal, candidate, review, admission, plan, and job exact replay;
- prove restart at both approval waits and after planning persistence;
- prove business and accounting approval ACK-loss redelivery;
- prove cross-scope, revoked authority, stale event, drift, and zero-mutation
  negatives;
- verify no duplicate financial or publication artifacts; and
- run focused Slice Gates with required coverage.

### CP-M1-E2E-FX-01B.6B.5: Installed Composition And 01B.7 Resume Decision

- bind the coordinator registry into the canonical installed AE process;
- verify Compose/OCI configuration and dependency readiness;
- prove the public-originated M1 request reaches existing scheduler ownership
  without runner state injection;
- record source, deployment, and fixture-residue evidence;
- execute the required Checkpoint Gate; and
- admit or deny resumption of CP-M1-E2E-FX-01B.7.

## 10. Verification Matrix

The 6B protected Gate SHALL prove at least:

~~~text
M1 WorkIntent selects registered product coordinator       = PASS
provider PLAN retained as non-authoritative evidence        = PASS
proposal preparation through existing product API           = PASS
business approval fresh authority reload                    = PASS
VoucherCandidate create/validate/review through EOS          = PASS
accounting approval and posting admission reload             = PASS
READY_FOR_D04 exact checkpoint                               = PASS
01B.5 materializer called only at READY_FOR_D04              = PASS
AgentPlan immutable save/exact replay                        = PASS
PlanValidation immutable save/exact replay                   = PASS
ExecutablePlan immutable save/exact replay                   = PASS
existing scheduler starts first ready step                   = PASS
restart at each wait and persistence boundary                = PASS
business approval ACK loss                                   = exact replay
accounting approval ACK loss                                 = exact replay
stale/out-of-order/revoked event                              = denied
cross-tenant/company/requester probe                          = zero disclosure
duplicate proposal/candidate/plan/job/Journal                 = 0
fixed tenant/Project/amount/currency/ratio/ID branch          = 0
runner direct state mutation                                 = 0
generic compiler/scheduler/worker M1 branch                   = 0
unauthorized database migration                              = 0
zero residue after protected smoke                           = PASS
~~~

Actual PostgreSQL evidence is required for the protected Gate. Remote
generation, embedding, and reranker providers are not required to close the
focused 6B product-wiring boundary. The live generation provider and
authenticated browser are required by the resumed 01B.7 acceptance.

## 11. Prohibited Shortcuts

The following cannot close 6B:

- invoking preparation or materialization only from tests or a smoke runner;
- creating a second M1 execution daemon or scenario-specific runtime;
- compiling the live provider PLAN as financial authority;
- hardcoding a tenant, company, Project, account, amount, currency, FX rate,
  approval, Plan, ratio, or evidence ID;
- treating an approval notification as approval proof;
- relabeling BUSINESS_FORMAL as WORK_RESULT or NSL_APPROVAL;
- persisting a checkpoint in unrelated prompt, error, or metadata fields;
- directly changing AgentExecution state from Playwright or test code;
- calling EOS private repositories or SQL from AE;
- bypassing the existing AgentPlan, validation, compiler, scheduler, worker,
  or result integration;
- introducing a migration without the stop decision required by this
  document; or
- claiming 01B.7 success before the installed path schedules real D12/D04
  work from a public-originated WorkIntent.

## 12. Stop Conditions

Implementation stops for an explicit decision if:

1. the current wait and event schemas cannot represent business and
   accounting approval without semantic overloading;
2. a pre-plan preparation checkpoint cannot be made restart-safe using
   current authoritative storage;
3. the current AgentPlan version rules cannot preserve provider evidence and
   admit the final deterministic plan for one execution;
4. owner-service APIs cannot reload exact approval authority after restart;
5. scheduler idempotency cannot prevent a duplicate RuntimeJob after crash;
6. product coordination requires fixed M1 business values in generic runtime
   code;
7. a new table, column, wait type, or event type becomes necessary; or
8. 01B.7 would still require a runner to call a private component or mutate
   runtime state.

Any stop report must identify the exact source constraint, violated
invariant, smallest correction, migration impact if any, and affected
regression matrix.

## 13. Closure And Resume Rule

CP-M1-E2E-FX-01B.6B closes only when a public-originated M1 WorkIntent is
routed through the immutable product coordinator registration, survives both
authoritative approval waits, reaches READY_FOR_D04, materializes and
persists the deterministic D12/D04 plan through existing repositories, and
starts execution through the existing scheduler without fixture-driven state
or runner-only orchestration.

Closure additionally requires exact replay, restart, approval ACK-loss,
cross-scope denial, zero duplicate, zero unauthorized migration, and
anti-fixture evidence against actual PostgreSQL.

Only after that evidence is recorded may CP-M1-E2E-FX-01B.7 resume. The
resumed Slice owns live Qwen3.5-9B provider evidence, authenticated
Playwright, the complete public M1 journey, Repository Full Gate, coverage,
and final zero-residue closure. It may not reopen or bypass the coordinator,
preparation, plan persistence, or scheduling boundaries closed here.
