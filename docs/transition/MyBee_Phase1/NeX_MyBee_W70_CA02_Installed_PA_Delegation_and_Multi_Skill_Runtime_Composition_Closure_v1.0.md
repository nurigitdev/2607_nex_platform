# NeX MyBee W70-CA02: Staged Golden A Retirement and Installed PA Multi-Skill Runtime Composition Closure v1.0

## 1. Status And Authority

- Decision date: `2026-11-15`
- Status: `DESIGN_CLOSED_IMPLEMENTATION_REQUIRED`
- Repository: `nurigitdev/2607_nex_platform`
- Reviewed branch: `codex/mybee-phase1-implementation`
- Reviewed source commit: `ac83f9b30fb3334b70615ef2c44ea9a609354ee7`
- Runtime code changes by this document: none
- Database migration authorized by this document: none by default
- Remote model-provider dependency for this document: none

This controlled amendment records the source-backed structural gap found when
entering `CP-M1-E2E-FX-01` after the successful `CP-M1-MB8-01` signed
D04/D12 Skill and Project Agent orchestration checkpoint. It also authorizes
the staged retirement of Golden A from active product selection and installed
deployment while preserving immutable historical evidence and reusable
runtime mechanisms.

The signed release, Product Capability Registry entries, deterministic PA
plan, controlled Journal adapters, and service business APIs are valid
checkpoint assets. They are not, by themselves, proof that the installed AE
runtime can accept a public IA request, delegate it to a PA, plan the claimed
work, select both signed Skills, and execute the complete journey.

This document supplements without rewriting:

- `NeX_MyBee_W70_CA01_NSL_Tool_Product_Capability_Registry_and_Skill_Pack_Entry_Reconciliation_v1.0.md`;
- `CP-M1-S8-02` controlled Journal execution evidence;
- `CP-M1-MB8-01` signed Skill and PA orchestration evidence; and
- the `CP-M1-E2E-FX-01` scope frozen in the Phase-1 Slice Plan v1.2.

Where W70-CA01 can be read as permitting direct progression from the signed
checkpoint to the public E2E, this amendment takes precedence and requires
the installed runtime-composition closure defined below. It also supersedes
W70-CA01 only where that document keeps Golden A in `ACTIVE_COMPATIBILITY` for
the duration of W70. Historical aliases and artifacts remain immutable, but
new product selection is frozen before M1 runtime implementation begins.

## 2. Entry Finding And Decision

`CP-M1-E2E-FX-01` must not be implemented as a test-only orchestration that
directly invokes EOS or WC private state. The current source does not yet
provide every installed product connection required by Gate B.

The W70 M1 sequence is therefore amended as follows:

1. complete `CP-M1-GA-RET-01: Golden A Selection Freeze and Retirement
   Preparation`;
2. complete `CP-M1-E2E-FX-01A: Installed PA Delegation and Multi-Skill
   Runtime Composition Closure`;
3. prove its focused regression and actual PostgreSQL protected Gate;
4. complete `CP-M1-GA-RET-02: Golden A Active Binding Removal and Historical
   Quarantine`; and
5. return to the original `CP-M1-E2E-FX-01` for the public browser/API,
   live-generation, accounting, allocation, P&L, WA, replay, and Full Gate.

The two retirement Slices and `CP-M1-E2E-FX-01A` are corrective prerequisites
inside the existing W70 M1 E2E packet. They do not add a new milestone, relax
the original acceptance criteria, or close any later M2 packet.

## 3. Confirmed Foundations

The corrective Slice must reuse the following completed foundations rather
than create parallel implementations:

| Foundation | Current authority | Required reuse |
| --- | --- | --- |
| Agent runtime persistence and scheduling | AE AgentExecution, ExecutablePlan, dispatcher, worker, and multi-step engine | Existing durable execution and JobQueue paths remain the execution SoR |
| Claimed-work admission | `AgentRuntimeAdmission` and `/internal/v1/work-handoffs` | WC handoff admission remains the only installed claimed-work entry |
| Background planning | `BackgroundAgentPlanningService` and deterministic semantic candidate admission | Product composition must invoke the existing service after durable claim admission |
| Delegation and resume | `P7DelegateWorkExecutor`, WC WorkResult delivery, AE wait/resume, and result publication | Existing delegation lineage and replay behavior remain authoritative |
| Signed M1 release | `ae-mybee-m1-signed-skill-checkpoint.v1.json` and signed NSP | Exact signature, Skill identity, semantic hash, Tool contract, FL binding, and release hash remain binding |
| Product registry | `ae-product-capability-registry.mybee-m1.v1.json` | Preserve this immutable mixed checkpoint release; create a successor active release without Golden A rather than mutating it |
| PA invocation plan | `build_pa_nsl_invocation_plan()` | ACTIVE Project/PA and exact `FL0012005 -> FL0004009` ordering remain mandatory |
| D12 READ | `PROJECT.WORK_CODE_SET.GET` and admitted D12 Skill | The installed runtime must use the existing EOS Project work-code authority |
| D04 controlled WRITE | Journal execution, verification, reconciliation, approval resume, idempotency, and UNKNOWN handling adapters | No direct Journal insert or alternate write engine is permitted |
| Business authorities | OA, WC, EOS, WA, allocation, and Project P&L APIs | Existing service contracts and actual PostgreSQL authorities remain the only business SoRs |

## 4. Source-Backed Structural Gaps

### 4.1 Installed AE Executor Profile Is Still Golden-A-Specific

`services/nex-ae-api/nex_ae_api/product_runtime_profile.py` constructs one
`ProductControlledSkillRuntime` and passes its dependencies and handlers to
the default executor registry. Its default paths and configuration still bind
the historical Golden A bundle and Skill root.

`services/nex-ae-api/nex_ae_api/product_controlled_skill.py` also fixes the
product capability to `FINANCE.CREATE_VOUCHER_DRAFT`. This proves the
installed controlled-WRITE mechanism but does not yet route the signed M1
D04/D12 capability set.

### 4.2 The Installed NSL Adapter Admits Exactly One Skill Source

`services/_shared/nex_runtime/nsl_runtime_adapter.py::InstalledNslPackage`
requires exactly one `*.ns` source and exposes one loaded Skill. The signed M1
release contains two exact Skills selected by two capability registrations.

The correction must introduce a product-level exact-Skill selection layer
above the existing one-Skill execution adapter. It must not weaken the
one-Skill identity check, load an arbitrary source by filename, or change NSL
compiler/runtime semantics.

### 4.3 Signed Release Admission Is Not Installed Execution Composition

The M1 registry and release lock correctly mark the D04/D12 capabilities as
signed and runtime-selectable. The checkpoint admission validates their
source, artifact, package, signature, semantic, Tool, OA action, and FL
bindings. The canonical Compose and OCI runtime still reference the Golden A
registry and bundle, as intentionally recorded by `CP-M1-MB8-01`.

An immutable release descriptor becoming `runtime_selectable=true` is an
admission decision. Installed process configuration, exact-Skill loading,
handler construction, readiness, and rollback evidence are separate runtime
decisions and remain open.

### 4.4 Claim Handoff Stops At Durable Admission

`services/nex-ae-api/nex_ae_api/claim_handoff_api.py` authenticates the WC
caller and invokes `admit_claimed_work()`. It returns the admitted execution
but does not invoke background planning or schedule the first executable
step.

`BackgroundAgentPlanningService.plan_claimed_execution()` already validates
the durable claimed-work source, resolves trusted Project context, admits and
compiles a candidate, and reuses the existing execution ID. It is currently
exercised as a component but is not composed into the installed claim-handoff
process.

The installed flow therefore lacks this required transition:

```text
WC ClaimExecutionHandoff
  -> durable AgentExecution admission
  -> background semantic planning/admission
  -> persisted ExecutablePlan
  -> schedule_next()
  -> installed dispatcher/worker execution
```

### 4.5 Active Planning Prompt Prohibits Delegation

The current active plan-candidate prompt in
`services/nex-ae-api/nex_ae_api/prompts.py` restricts output to
`LOCAL_CAPABILITY` and `REPORT` and explicitly prohibits `DELEGATE_WORK` and
WC references. The parser and compiler have delegation support, but the
active generation contract cannot produce that path.

The M1 public IA journey needs an admitted, versioned delegation-capable
planning profile. It must be narrowly scoped and must not reinterpret an LLM
response as Project, approval, accounting, or authorization authority.

### 4.6 Public IA Project Scope Is Not Yet A Trusted Delegation Input

The ordinary IA interaction path does not automatically provide a trusted
Project ID to semantic admission. A Project may be mentioned in natural
language, but an LLM-extracted Project string cannot become authority.

For M1, the public path must resolve an explicit user-facing Project Code
against current EOS/OA authority, produce the stable internal Project
reference, and either:

- delegate to the active PA for the resolved Project; or
- fail closed or ask for clarification when the Project is missing,
  ambiguous, inactive, or unauthorized.

The UI and evidence may display the user-facing Project Code. Durable foreign
keys and existing service contracts retain their current canonical IDs.

### 4.7 Installed Deployment And Golden Runner Still Select Golden A

The canonical AE runtime Containerfile, Compose overlay, installed acceptance,
and Golden Journey runner currently select the Golden A registry, bundle, and
authority profile. They do not yet install or execute the M1 registry and
signed D04/D12 release.

Promoting M1 must be additive and rollback-capable. This document is the
retirement decision: Golden A first becomes unavailable for new product
selection while its current installed assets remain a bounded rollback input;
after the generalized M1 runtime passes protected acceptance, those active
bindings are removed and only historical/replay evidence remains.

### 4.8 Product Intent And Consumer Builders Still Return One Fixed Capability

The generic `DomainIntentActivatorRegistry` and `ProductCapabilityRegistry`
already support multiple immutable registrations. However,
`services/nex-ae-api/nex_ae_api/domain_intent_products.py` currently builds
only the Golden A finance registration, and
`services/nex-ae-api/nex_ae_api/mybee_product_consumer.py` resolves the same
fixed capability.

These modules identify a composition refactoring point. M1 must be admitted by
contributing capability-keyed product registrations to a generic builder. It
must not be added as another `if/elif` branch, another one-capability builder,
or a parallel MyBee-only runtime.

## 5. Normative Decisions

### W70-CA02-ADR-01: Compose Existing Product Components

The correction is runtime composition, not a new Agent Runtime.

Implementation must reuse the existing:

- public IA authentication, interaction, and progress boundaries;
- WC delegation, claim, assignment, delivery, and ACK lineage;
- AE claimed-work admission and background planning services;
- AgentExecution, ExecutablePlan, scheduler, dispatcher, worker, and result
  finalization components;
- signed release and Product Capability Registry admission;
- NSL v0.2.1 READ and controlled-WRITE adapters; and
- OA, EOS, WC, WA, allocation, and Project P&L service APIs.

No test harness may own a transition that the installed product does not own.

### W70-CA02-ADR-02: Keep Planning Semantic And Authority Deterministic

Live generation may classify intent and propose a plan. Admission must bind
the proposal to:

- a freshly resolved, authorized, ACTIVE Project;
- its synchronized ACTIVE PA;
- current Project work-code context containing `FL0012005` and `FL0004009`;
- exact registered capability and Skill identities;
- canonical schemas and deterministic payload hashes; and
- fresh OA/WC/EOS authority and approval evidence.

Model output cannot supply or override Project membership, Project lifecycle,
accounting proof, FX evidence, approval state, idempotency identity, Posting
outcome, allocation result, or P&L authorization.

### W70-CA02-ADR-03: Add A Verified Multi-Skill Product Selection Layer

Installed M1 execution uses a verified release catalog that selects one exact
Skill for each executable step by:

```text
capability_id
  -> exact Product Capability Registry registration
  -> signed release and bundle lock
  -> exact Skill ID/version/semantic hash/artifact hash
  -> exact Tool catalog and handler set
  -> one-Skill InstalledNslExecution
```

The selection layer must fail closed on an unknown capability, duplicate
selector, alias ambiguity, missing release, signature mismatch, Skill or Tool
hash mismatch, unsupported backend profile, absent handler, or cross-release
substitution.

The existing one-Skill `InstalledNslPackage` identity invariant remains. A
new product catalog or factory may construct an exact per-Skill execution
view from the admitted signed release; it must not turn the adapter into an
unverified directory loader.

### W70-CA02-ADR-04: Separate Project Resolution, Delegation, And Execution

The public IA boundary resolves and authorizes the Project before delegation.
WC persists delegation and claim authority. AE admits the claimed source,
plans against trusted context, persists the plan, and schedules it. PA/NSL
then executes only the admitted plan.

These stages retain separate evidence and idempotency identities. A retry may
reuse an admitted execution only when tenant, requester, Project, WorkItem,
source hash, capability set, and semantic request are identical.

### W70-CA02-ADR-05: Promote M1 Through Immutable Deployment Inputs

Canonical Compose and OCI packaging must receive explicit immutable M1
registry, signed release, Tool catalog, public key, and Skill artifact inputs.
Readiness verifies the complete set before the worker claims work.

Before `CP-M1-E2E-FX-01A` passes protected acceptance, deployment rollback may
use the last admitted Golden A configuration as a temporary recovery input,
but Golden A remains unavailable for new public planning. After
`CP-M1-GA-RET-02`, rollback must target the last admitted generalized runtime
release, not Golden A. No historical registry, bundle lock, or signed release
may be mutated in place.

### W70-CA02-ADR-06: Prefer No Migration

The source audit has not identified a new authoritative entity. Existing AE
execution/plan/job/result tables, WC WorkItem/Claim/Assignment/delivery state,
and EOS/WA authorities should be sufficient.

A database migration is prohibited unless implementation proves that a
durable product state cannot be represented without overloading an existing
contract. That finding requires a separate decision before migration work.

### W70-CA02-ADR-07: Fixtures May Seed Authorities But Never Drive Runtime

The Golden Journey testing contract remains binding. Before the public
request, a protected runner may seed acceptance-owned tenant, identity,
Project, Project Agent, account, period, FX, approval-policy, allocation, and
capability records through the owning service's supported seed or
administrative boundary. After the request enters the Platform, the installed
runtime must resolve every business value from the public request, durable
runtime state, or an authoritative service.

The minimum runtime data-origin matrix is:

| Runtime value | Authoritative origin | Prohibited substitute |
| --- | --- | --- |
| tenant and requester | authenticated OA-backed session/token and persisted interaction | fixed `VO00`, employee ID, or test principal in product code |
| user-facing Project Code | public request followed by EOS Project resolution and fresh OA entitlement | fixture Project UUID/code or model-generated authority |
| Project Agent | synchronized AE Project Agent projection for the resolved ACTIVE Project | scenario-owned PA ID |
| company, document, vendor, amount, currency, date, and requested allocation | public request persisted in WorkIntent/claimed planning source plus owning service validation | Golden JSON fixture or module constant |
| account, period, approved FX snapshot, Posting proof, and allocation authority | current EOS/WC/OA service APIs and PostgreSQL-backed SoRs | embedded Account code, rate, proof, or success result |
| capability and exact Skill | Product Capability Registry plus admitted signed release | filename, directory order, test mapping, or prompt text |
| execution and result state | AE/WC/EOS/WA durable product transitions | runner-owned insert/update or fabricated WorkResult |

Product runtime code, its transitive import graph, active OCI context, and
canonical Compose configuration must not read or require:

```text
scripts/smoke/data/*
scripts/deployment/data/*
NEX_AE_DEMO_*
NEX_*_FIXTURE*
p8_demo_semantic_activation
p8_demo_controlled_skill
golden_a_approval_journey
```

Historical compatibility modules and acceptance seed files may remain in the
repository. They cannot be imported by, copied into, or configured as an
authority for the active M1 product process.

### W70-CA02-ADR-08: Generalize By Registration, Not By M1 Branches

D04 and D12 are the first product admissions to the generalized runtime; they
must not become special cases inside the runtime factory.

The product composition must use independent immutable registrations for:

1. semantic intent activation by exact capability identity through the
   existing `DomainIntentActivatorRegistry` boundary;
2. capability-to-Skill binding through `ProductCapabilityRegistry`;
3. signed release and exact Skill selection through the verified release
   catalog/factory; and
4. canonical operation-to-handler construction through an admitted operation
   adapter registry or equivalent immutable mapping.

The generic composition layer must not contain scenario-specific branches
such as:

```text
if capability == FINANCE.VOUCHER.APPROVE_AND_POST
if skill == MYBEE.D04.JOURNAL_POSTING
if tenant == VO00
if project == Project A
if amount == 10000 or rate == 1350.20
```

Capability-specific policy and payload mapping may exist in a domain-owned
activator or operation adapter registered under its exact identity. The
generic dispatcher, worker, NSL selector, and installed process must depend
only on their registry/protocol contracts.

Golden A may remain represented only in its immutable historical registry and
replay evidence. It must not be copied into the successor active registry or
the generalized installed composition. Implementation must not add M1 as a
second hard-coded sibling to the existing Golden A hard-coding. A product
builder that returns one fixed Golden A registration is therefore a required
refactoring point, not a template for a second fixed registration.

M1 names may remain in immutable release IDs, evidence IDs, and acceptance
reports. Active product module names, environment variable names, process
entrypoints, and generic runtime schemas must describe capability, Skill,
release, or operation concepts rather than a Golden scenario.

### W70-CA02-ADR-09: Acceptance Must Exercise The Same Installed Composition

The final W70 Golden Journey must comply with
`docs/testing/Golden_Journey_Platform_Integration_Testing_Contract_v1.0.md`.
Its runner must be registered as `GOLDEN_JOURNEY` and pass the transition
audit. After the browser/API request begins, the runner may only use public
interaction, public/read-only polling, declared process restart, assertion,
and acceptance-owned cleanup.

The following identities prepared and protected-tested as the generalized
successor in `01A`, activated in `RET-02`, and exercised by the final protected
E2E must match:

- AE OCI image digest and packaged entrypoint;
- Compose service command and runtime profile;
- Product Capability Registry hash;
- signed release/package/public-key hashes;
- admitted NSL wheel lock and backend profile;
- intent-activator registry projection;
- operation-adapter registry projection;
- required dependency readiness projection; and
- service trust profile.

A test-only composition factory, alternate executor profile, private handler
injection, monkeypatch of a transition owner, or runner-local Skill loader
cannot produce product acceptance evidence.

### W70-CA02-ADR-10: Require Hard-Coding Resistance Evidence

The fixed Golden M1 values remain the final business acceptance vector, but a
single fixed vector cannot prove product generality. Before the final E2E, the
corrective Slice must pass a deterministic variation matrix through the same
public admission and installed composition boundaries.

At minimum, the matrix changes independently:

- tenant/requester and authorization outcome;
- Project Code and Project Agent;
- amount, currency, and transaction date;
- approved FX snapshot identity and rate;
- account/document/evidence references;
- allocation target Projects and ratios; and
- capability registration order without changing the canonical registry
  projection.

The matrix includes at least two positive cases with different business
values plus negative cases for unknown, ambiguous, inactive, unauthorized,
stale, mismatched, and cross-tenant inputs. Assertions derive expected values
from submitted input and authoritative read models rather than copying the
runtime's result fixture.

An automated product-residue audit must inspect active product modules,
transitive imports, OCI inputs, Compose variables, and installed entrypoints
for forbidden Demo/fixture dependencies and M1 business constants. The audit
runs in the corrective Slice Gate, final protected Gate, and Repository Full
Gate.

### W70-CA02-ADR-11: Retire Golden A In Two Controlled Stages

Golden A retirement distinguishes product selection from physical asset
removal so that the active runtime is never left without an admitted recovery
path.

#### Stage 1: CP-M1-GA-RET-01 Selection Freeze And Retirement Preparation

This stage completes before `CP-M1-E2E-FX-01A` and must:

1. freeze all new Golden A features, registrations, prompts, fixtures, and
   deployment dependencies;
2. remove `FINANCE.CREATE_VOUCHER_DRAFT` and its historical Skill from public
   IA intent selection, new planning, and new capability snapshots;
3. mark the capability and aliases `DEPRECATED` or `REPLAY_ONLY` in a new
   immutable retirement projection without editing historical registries;
4. drain or explicitly reconcile any pre-existing Golden A execution before
   disabling new selection;
5. classify every Golden A source, test, script, lock, profile, and deployment
   reference as `GENERALIZE`, `REMOVE_ACTIVE`, `REPLAY_ONLY`, or `HISTORY`;
6. capture the last known-good runtime, registry, bundle, and evidence hashes
   as a bounded temporary rollback receipt; and
7. install a gate proving that no new WorkIntent, semantic candidate,
   ExecutablePlan, or RuntimeJob can select Golden A.

Stage 1 does not delete the currently packaged Golden A runtime files. They
remain temporarily available only for bounded rollback and historical replay
while the generalized replacement is implemented. This temporary presence is
not active product support.

#### Stage 2: CP-M1-GA-RET-02 Active Binding Removal And Historical Quarantine

This stage runs only after `CP-M1-E2E-FX-01A` passes its protected PostgreSQL,
readiness, restart, variation, and same-composition Gates. It must:

1. publish a successor active Product Capability Registry that excludes
   Golden A while retaining D04/D12 and future product registrations;
2. remove Golden A authority-profile, bundle, Skill-root, and scenario
   variables from canonical Compose and OCI inputs;
3. remove Golden-specific active imports, constants, activator/consumer
   builders, prompt branches, and runtime handler binding;
4. migrate reusable state-machine, approval, replay, UNKNOWN, verification,
   and reconciliation coverage to fixture-independent generic tests;
5. quarantine remaining Golden scenario tests and scripts as historical
   evidence or remove them after equivalent generic coverage is demonstrated;
6. change the runtime rollback target to the last admitted generalized M1
   release; and
7. prove the active product import graph, image, Compose configuration,
   environment, registry, readiness, and public capability projections contain
   no Golden A dependency.

The underlying EOS voucher-draft API and compatibility alias are not deleted
merely because the scenario retires. They remain deprecated until caller
inventory proves zero unresolved use and a later API-retirement decision
authorizes removal.

#### Historical Preservation Matrix

| Asset class | Retirement treatment |
| --- | --- |
| frozen design and Slice documents | preserve as history |
| immutable registry, bundle, signature, digest, and evidence receipts | preserve unchanged for audit/replay |
| database migrations and persisted historical lineage | preserve; no destructive cleanup |
| generic Agent Runtime, approval, controlled-WRITE, replay, verification, reconciliation, and publication mechanisms | retain and cover with fixture-independent tests |
| Golden authority profile, scenario fixture, fixed activator/consumer, prompt branch, and active deployment binding | remove from active product after replacement Gate |
| old public/API alias | deprecate first; remove only after zero-caller evidence and separate decision |
| acceptance data | allow only as pre-request seed; never runtime authority |

## 6. Corrective Slice: CP-M1-E2E-FX-01A

### 6.1 Scope

`CP-M1-E2E-FX-01A: Installed PA Delegation and Multi-Skill Runtime
Composition Closure` performs the minimum product changes required before the
public M1 E2E:

1. add a versioned, capability-registered IA planning/delegation profile that
   can emit an admitted `DELEGATE_WORK` plan for an explicitly resolved
   Project without a scenario-specific branch in semantic admission;
2. connect authenticated IA intent to fail-closed Project-Code resolution,
   current OA entitlement, and active PA selection;
3. compose claim handoff admission with the existing background planning
   service, plan persistence, and `schedule_next()` transition;
4. add the generic verified signed-release Skill catalog/factory and
   operation-adapter registry, then admit exact D12/D04 step routing as its
   first MyBee product registrations above the existing NSL execution
   adapters;
5. bind D12 READ to current Project work-code context and D04 WRITE to the
   existing approval, execution, verification, UNKNOWN, and reconciliation
   adapters;
6. promote immutable M1 registry/release inputs into canonical AE OCI and
   Compose configuration with readiness, same-composition, and rollback
   checks;
7. preserve immutable Golden A historical evidence while retaining all
   fixture-independent P4-P8/P7/GB2 runtime regression;
8. add the product-residue and Golden Journey transition audits; and
9. record source, variation-matrix, focused test, actual PostgreSQL,
   deployment, and evidence proving that no fixture authority or private-state
   shortcut was used.

### 6.2 Out Of Scope

The corrective Slice does not:

- execute or declare the final public Golden journey;
- add new business accounting behavior;
- change EOS, OA, WC, or WA business authority;
- change the NSL language, compiler, runtime, or public API;
- activate the other 16 W70 candidate Tools;
- delete or mutate Golden A historical registries, locks, signatures,
  migrations, or evidence;
- add a database migration by default;
- treat a model response as approval or accounting evidence; or
- replace installed composition with a smoke-only provider.

### 6.3 Required Verification

Focused verification must include:

- delegation-capable prompt/profile positive, malformed, ambiguous Project,
  inactive Project, unauthorized Project, and unsupported-intent cases;
- WC handoff admission -> background plan -> persisted plan -> scheduling
  transition and exact replay behavior;
- signed multi-Skill selector positive cases for D12 and D04;
- unknown capability, wrong version/hash/signature, absent handler, stale
  registry, alias collision, and cross-release negative cases;
- D12 READ before D04 WRITE ordering and fail-closed dependency behavior;
- restart between handoff, planning, scheduling, approval wait, resume,
  verification, and result finalization;
- duplicate handoff, duplicate claim, duplicate resume, and lost-ACK replay;
- canonical OCI/Compose source checks and worker readiness;
- product import, environment, OCI, Compose, fixed-business-value, and Demo
  residue audit;
- at least two non-identical positive business inputs through the same
  capability-registered runtime plus negative variation cases;
- Golden Journey runner registration and transition-ownership audit;
- actual AE, WC, EOS, and OA test PostgreSQL protected smoke; and
- the `CP-M1-GA-RET-01` no-new-selection Gate and historical replay evidence.

Remote generation is optional for the corrective Slice. Deterministic
candidate fixtures may verify composition, but they must enter through the
same installed admission, planning, persistence, scheduling, and execution
boundaries used by production. The final E2E remains responsible for live
generation.

### 6.4 Closure Conditions

`CP-M1-E2E-FX-01A` closes only when:

1. a public-path IA request can produce an admitted Project-scoped delegation
   without direct service-private calls;
2. WC claim handoff automatically reaches a scheduled durable PA plan;
3. the installed worker selects and executes exact signed D12 and D04 Skills;
4. approval wait/resume, controlled WRITE, verification, reconciliation, and
   result publication remain restart- and replay-safe;
5. canonical Compose/OCI readiness recognizes the complete M1 release set;
6. the runtime consumes no business fixture and contains no M1 scenario-value
   branch;
7. two different admitted input sets execute without changing product code or
   runtime configuration;
8. no new Golden A selection is possible and its immutable historical evidence
   remains verifiable; and
9. actual PostgreSQL evidence proves the installed path rather than a test
   substitute.

## 7. Original CP-M1-E2E-FX-01 After Correction And Retirement

After `CP-M1-E2E-FX-01A` and `CP-M1-GA-RET-02` close, the original Slice
resumes without reducing its scope. It must prove one protected public Golden
M1 journey:

```text
authenticated IA browser/API request
  -> explicit Project resolution and PA delegation
  -> WC claim and AE installed background planning
  -> D12 Project work-code READ
  -> WC business approval and fresh OA/accounting authority
  -> human accountant approval
  -> D04 NSL controlled Journal CREATE
  -> EOS verification/reconciliation
  -> USD 10,000 x KRW 1,350.20 = KRW 13,502,000
  -> deterministic allocation
       Project A = KRW 5,400,800
       Project B = KRW 8,101,200
  -> authorized Project P&L projection/read
  -> PA WorkResult and WA result consumption
  -> IA user-visible final result
```

The final Gate requires:

- actual OA, AE, WC, EOS, and WA PostgreSQL authorities;
- signed service trust and current authorization;
- the admitted signed M1 registry and Skill release;
- live Qwen3.5-9B generation for natural-language semantic planning;
- authenticated Playwright acceptance through public routes;
- the canonical registered Golden Journey runner and transition audit;
- the same successor OCI image, entrypoint, runtime profile, Golden-free
  active registry, signed release, and operation-adapter projections prepared
  by `01A` and activated by `RET-02`;
- exact FX, approval, payload, Journal, allocation, P&L, Skill, plan,
  WorkResult, and result-publication lineage;
- retry and lost-ACK proof with no duplicate Journal or allocation;
- tenant, Project, payroll/P&L privacy, and unauthorized-read negatives;
- restart and UNKNOWN/reconciliation recovery;
- zero-residue cleanup; and
- Repository Full Gate plus W70 closure evidence.

## 8. Prohibited Shortcuts

The following cannot satisfy either corrective or final acceptance:

- direct inserts or updates to AE runtime-transition state;
- direct EOS Journal, allocation, or P&L calls from an E2E harness in place of
  PA/NSL execution;
- direct WC Claim/Assignment/approval state mutation;
- hard-coded successful WorkResult, Journal, allocation, P&L, or WA payloads;
- a test-only runtime factory not used by the installed process;
- a Golden/M1-specific branch in generic semantic admission, dispatch,
  worker, NSL selection, or process composition;
- a runtime read of an acceptance fixture, fixed tenant, Project, employee,
  account, amount, currency, rate, allocation, or expected result;
- a model-selected Project or authority without deterministic service
  resolution and authorization;
- bypassing the signed release because the same `.ns` source compiles;
- selecting a Skill by directory order or filename alone;
- marking a capability active only in test configuration; or
- declaring M1 from component tests without the public Playwright journey.

## 9. Recommended Implementation Order

| Order | Boundary | Deliverable |
| --- | --- | --- |
| 1 | `W70-CA02` | This source-backed gap, decision, and entry contract |
| 2 | `CP-M1-GA-RET-01` | Golden A new-selection freeze, inventory classification, drain/reconciliation, bounded rollback receipt, and retirement Gate |
| 3 | `CP-M1-E2E-FX-01A.1` | Source/refactoring checkpoint, data-origin matrix, residue baseline, and exact installed composition map |
| 4 | `CP-M1-E2E-FX-01A.2` | Registry-driven trusted Project resolution and delegation-capable IA planning profile |
| 5 | `CP-M1-E2E-FX-01A.3` | Claim handoff -> background planning -> plan persistence -> scheduling wiring |
| 6 | `CP-M1-E2E-FX-01A.4` | Generic verified multi-Skill/operation registries and first D12/D04 product registrations |
| 7 | `CP-M1-E2E-FX-01A.5` | Canonical OCI/Compose promotion, variation matrix, residue/transition audits, readiness, rollback, and protected PostgreSQL Gate |
| 8 | `CP-M1-GA-RET-02` | Golden A active registry/config/code removal, historical quarantine, generalized rollback, and zero-active-residue Gate |
| 9 | `CP-M1-E2E-FX-01` | Public live Golden M1 journey, Playwright, replay/recovery, Full Gate, and W70 closure |

The `.1` through `.5` labels are implementation checkpoints within one
corrective Slice. They may be separate commits, but they do not become
independent roadmap packets unless a later decision explicitly splits them.
`RET-01` and `RET-02` are independent corrective Slices because each changes
the active selection or deployment state and requires its own rollback and
evidence boundary.

## 10. Stop Conditions

Implementation stops for a new decision if:

1. a new authoritative table or migration appears necessary;
2. NSL v0.2.1 compiler/runtime/public API changes appear necessary;
3. the signed NSP cannot yield exact independently selected D04/D12 execution
   views without weakening signature or semantic-hash admission;
4. Project resolution cannot be based on current EOS/OA authority;
5. the claimed-work transition requires direct runtime-state SQL;
6. D04 execution would bypass existing approval, Posting, verification, or
   reconciliation boundaries;
7. Stage 1 cannot preserve a bounded Golden A rollback until the generalized
   M1 replacement passes protected acceptance;
8. a product transition exists only in a smoke runner; or
9. actual PostgreSQL or signed-service-trust verification is unavailable at a
   required protected Gate;
10. active product code or packaging needs an acceptance fixture, fixed
    tenant/Project/business value, Demo module, or scenario-specific process
    entrypoint; or
11. D04/D12 activation requires capability-specific branching in a generic
    runtime owner instead of an admitted registration/adapter;
12. Stage 1 cannot prove that new Golden A selection is impossible while
    preserving in-flight reconciliation; or
13. Stage 2 would remove historical audit/replay evidence, a database
    migration, or an API alias that still has unresolved callers.

## 11. Productization Design Review Result

The post-GB2 productization review records the following state at the reviewed
commit:

| Productization criterion | Current source state | Design disposition |
| --- | --- | --- |
| Generic installed runtime composition | Existing and active | Reuse without a parallel MyBee runtime |
| Capability-keyed intent activator registry | Generic registry exists; product builder returns one Golden A registration | Freeze Golden selection in `RET-01`; generalize contribution/composition in `01A.2` |
| Immutable Product Capability Registry | Existing M1 registry contains Golden A, D04, and D12 exact bindings | Preserve the historical release; publish a Golden-free successor in `RET-02` |
| Runtime business input authority | Golden A product path was previously generalized, but M1 installed mapping is absent | Enforce ADR-07 data-origin matrix in `01A.1` and `01A.2` |
| Signed multi-Skill release admission | D04/D12 signature, hashes, and bindings are admitted | Add generic exact-Skill execution selection in `01A.4` |
| Operation-specific adapters | D12 READ and D04 execution/verification/reconciliation components exist | Register adapters; do not branch in generic runtime |
| Claim handoff to execution | Durable admission exists; planning and scheduling are not composed | Wire existing services in `01A.3` |
| Canonical deployment | Active AE image/Compose remains Golden-A-bound | Keep bounded rollback through `01A.5`, then remove active binding in `RET-02` |
| Fixture separation | Canonical GB2 contract exists; M1-specific enforcement is not yet installed | Add product-residue and variation audits in `01A.5` |
| Golden Journey enforcement | Canonical transition contract and audit exist | Register and enforce the new runner in final `CP-M1-E2E-FX-01` |

Design conclusion:

```text
productized target architecture       = ADEQUATELY DEFINED AFTER W70-CA02
current installed M1 implementation   = NOT YET PRODUCTIZED
Golden A new product selection        = RETIRE FIRST IN RET-01
Golden A active deployment binding    = REMOVE AFTER 01A IN RET-02
Golden A historical evidence          = PRESERVE IMMUTABLY
fixture-driven runtime design         = REJECTED
scenario-specific generic branching   = REJECTED
final public M1 E2E entry              = BLOCKED UNTIL RET-02 CLOSES
```

The design is ready to enter the corrective Slice because it now defines not
only the expected Golden outcome but also the reusable ownership boundaries,
runtime data origins, registration model, same-composition proof, and
hard-coding resistance evidence. Passing fixed Golden values alone cannot
close `01A` or the final E2E.

## 12. Closure Statement

```text
W70-CA01 Tool/Skill foundation          = CLOSED
CP-M1-S8-02 Journal checkpoint          = CLOSED
CP-M1-MB8-01 signed Skill checkpoint    = CLOSED
W70-CA02 design reconciliation          = CLOSED
CP-M1-GA-RET-01 selection freeze        = REQUIRED NEXT
CP-M1-E2E-FX-01A runtime composition    = BLOCKED BY RET-01
CP-M1-GA-RET-02 active binding removal  = BLOCKED BY 01A
CP-M1-E2E-FX-01 public M1 E2E           = BLOCKED BY RET-02
new Agent Runtime                       = PROHIBITED
test-only orchestration substitute      = PROHIBITED
runtime business fixture dependency     = PROHIBITED
scenario branch in generic runtime      = PROHIBITED
Golden Journey transition ownership     = PROHIBITED
NSL compiler/runtime change             = PROHIBITED
database migration                      = NOT AUTHORIZED BY DEFAULT
```

Implementation may begin with `CP-M1-GA-RET-01` only after this document is
admitted into the MyBee Phase-1 reading order. `CP-M1-E2E-FX-01A` may begin
only after the Stage 1 no-new-selection and in-flight reconciliation Gate
passes.
