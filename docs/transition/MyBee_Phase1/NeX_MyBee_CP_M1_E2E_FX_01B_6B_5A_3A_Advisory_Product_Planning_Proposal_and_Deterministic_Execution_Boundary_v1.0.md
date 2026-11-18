# NeX MyBee CP-M1-E2E-FX-01B.6B.5A.3A: Advisory Product Planning Proposal and Deterministic Execution Boundary v1.0

## 1. Status And Authority

- Decision date: 2026-11-18
- Status: DESIGN_CLOSED_IMPLEMENTATION_REQUIRED
- Repository: nurigitdev/2607_nex_platform
- Branch: codex/mybee-phase1-implementation
- Source-backed review commit: 968c43d6
- Parent amendment:
  `NeX_MyBee_CP_M1_E2E_FX_01B_6B_5A_Installed_Product_Coordinator_Authority_and_Dispatch_Closure_v1.0.md`
- Predecessor: CP-M1-E2E-FX-01B.6B.5A.3
- Suspended Slice: CP-M1-E2E-FX-01B.6B.5A.4
- Successors after closure:
  - CP-M1-E2E-FX-01B.6B.5A.4
  - CP-M1-E2E-FX-01B.6B.5A.5
- Database migration authorized by this document: none by default
- Remote generation provider: required only for provider-assisted acceptance;
  deterministic-only regression remains provider-independent

This controlled amendment closes the difference between the intended Product
planning contract and the installed public router. Product Coordinators need
model-assisted planning for ambiguous, compound, and cross-domain work, but a
generation provider cannot become business, approval, authorization, or
execution authority.

The platform therefore separates an advisory `ProductPlanningProposal` from
the authoritative `AgentPlan` and `ExecutablePlan`. The proposal is immutable
semantic evidence. The Product Coordinator is a durable governed-work
coordinator. The final executable plan remains deterministic output of exact
capability releases, owner-service authority, approval checkpoints, and an
admitted materializer.

## 2. Source-Backed Entry Findings

### 2.1 Intended Provider Evidence Is Not Reached

The existing design states that live provider INTENT and PLAN output may
recommend admitted Product capabilities and be retained as provenance. It
also prohibits that output from approving work, selecting financial
authority, or becoming the final D12/D04 executable plan.

The current implementation routes claimed work to the Product Coordinator
before invoking the PLAN semantic stage. A matching Product registration
therefore returns `PRODUCT_COORDINATION_STARTED` without producing provider
PLAN evidence. The implementation correctly prevents provider authority, but
it also removes advisory planning that future compound Product operations
need.

### 2.2 Product Coordinator Is Not A Cognitive Planner

The Product Coordinator currently owns durable preparation, wait/event
handling, fresh authority reload, approval progression, replay convergence,
and deterministic READY-state activation. Those responsibilities must remain
model-independent.

Embedding a live model call inside `begin()`, `resume()`, or READY activation
would make replay and restart dependent on a mutable external response. It
would also allow approval redelivery to produce another plan candidate.
Provider invocation must therefore occur before durable Product preparation,
and its exact admitted result must be passed by immutable reference.

### 2.3 One Planning Policy Does Not Fit Every Product

An exact single-capability READ or structured WRITE can be routed and
materialized without a model. Ambiguous natural language, multi-step work,
and cross-domain orchestration benefit from provider planning. Requiring a
provider for every operation would add unnecessary latency and availability
risk; forbidding it would force business decomposition into hard-coded
scenario logic.

Planning policy must be an immutable coordinator registration property, not
an environment-only switch or prompt-time guess.

## 3. Normative Planning Layers

### 3.1 Canonical Flow

The installed Product flow SHALL be:

```text
authenticated prompt or claimed WorkItem
  -> provider-assisted INTENT and CONTEXT evidence
  -> immutable WorkIntent and AgentContext
  -> exact Product capability and coordinator resolution
  -> optional or required ProductPlanningProposal generation
  -> deterministic proposal admission
  -> durable Product Coordinator preparation and approval checkpoints
  -> fresh owner-service authority resolution
  -> deterministic AgentPlan and ExecutablePlan materialization
  -> shared RuntimeJob, worker, executor, and result publication
```

The Product router may resolve the exact coordinator before proposal
generation so that it can select the registered planning policy and prompt
contract. It SHALL NOT begin durable Product preparation until the required
proposal decision has completed.

### 3.2 ProductPlanningProposal Contract

`ProductPlanningProposal` is a provider-neutral, immutable, hash-bound
semantic artifact. It may contain only:

- requested outcome and bounded goal summary;
- suggested admitted Product capability IDs;
- logical operation ordering and dependency edges;
- required-input and clarification declarations;
- expected output and completion criteria;
- concurrency or sequencing suggestions;
- confidence and calibration decision;
- prompt, model, deployment, and request provenance; and
- proposal schema version, payload hash, and storage reference.

The proposal SHALL NOT contain or decide:

- approval state, approval proof, or authority evidence;
- OA authorization or a service principal decision;
- owner-service private identifiers not present in admitted input;
- account, Project, AllocationPlan, VoucherCandidate, Journal, or evidence
  identities invented by the model;
- arbitrary endpoint, implementation, Skill version, or executor selection;
- final tool authorization or WRITE permission; or
- the canonical AgentPlan, ExecutablePlan, RuntimeJob, or business result.

Suggested capability identities are re-resolved against the immutable Product
Capability Registry. Exact capability and Skill versions come from the
registered release, never from provider output.

### 3.3 Proposal Persistence And Lineage

The existing semantic-candidate evidence and owner-private candidate storage
SHALL be reused. A proposal must be retrievable by tenant, owner, execution,
semantic stage, candidate hash, prompt binding, and model provenance.

The Product preparation checkpoint SHALL contain only a bounded proposal
reference and hash, not raw prompt or provider output. Exact replay uses the
same proposal. Restart or approval ACK redelivery cannot invoke the provider
again or change the proposal.

No provider proposal may be saved into the immutable AgentPlan repository.
The AgentPlan identity remains available for the final deterministic Product
plan produced at the registered READY checkpoint.

### 3.4 Coordinator Planning Policy

Each Product Coordinator registration SHALL bind exactly one of:

```text
DETERMINISTIC_ONLY
PROVIDER_ASSISTED_OPTIONAL
PROVIDER_ASSISTED_REQUIRED
```

- `DETERMINISTIC_ONLY`: provider PLAN is not invoked. Exact WorkIntent,
  capability, and authority contracts are sufficient.
- `PROVIDER_ASSISTED_OPTIONAL`: an admitted proposal may enrich sequencing or
  clarification. An explicitly registered deterministic fallback may proceed
  when the provider is unavailable. Silent fallback is prohibited.
- `PROVIDER_ASSISTED_REQUIRED`: durable Product preparation cannot start until
  one admitted proposal exists. Provider failure or failed calibration is a
  bounded retryable or terminal fail-closed outcome according to the
  registered policy.

The registration SHALL also bind proposal schema version, prompt binding,
admission policy identity, fallback identity if one exists, and whether the
proposal is consumed by the preparation adapter, final materializer, or both.
Changing any bound value creates a new registration hash and requires a new
activation lock.

### 3.5 Deterministic Proposal Admission

Admission SHALL verify:

1. exact WorkIntent, AgentContext, execution, and capability-snapshot lineage;
2. strict proposal schema and rejection of authority/private fields;
3. suggested capabilities are admitted for the exact Product release;
4. dependency graph validity and bounded size;
5. prompt and model provenance plus exact calibration policy;
6. candidate payload integrity and owner-private storage integrity; and
7. coordinator planning-policy compliance.

Failure creates no Product checkpoint, approval case, VoucherCandidate,
AgentPlan, ExecutablePlan, or RuntimeJob.

### 3.6 Final Plan Authority

The final AgentPlan and ExecutablePlan SHALL be materialized only from:

- exact WorkIntent and AgentContext;
- exact Product capability, coordinator, and Skill release;
- admitted proposal reference when the policy uses one;
- current owner-service authority and immutable approval evidence; and
- the exact READY checkpoint and registered materializer.

The materializer may use admitted proposal ordering and completion semantics,
but it must resolve all executable operations and inputs through registered
schemas and owner authority. Provider output cannot bypass validation or be
copied as an executable tool request.

## 4. READ, WRITE, And Cross-Product Rules

### 4.1 READ

Exact single-capability READ may use `DETERMINISTIC_ONLY`. Compound READ,
comparison, aggregation, and report requests may use provider assistance, but
all data access remains subject to OA and owner-service authorization.

### 4.2 WRITE

Provider assistance may propose operation ordering and missing information.
Every WRITE still requires registered operation schemas, fresh authority,
required human approval, idempotency, checkpointing, controlled execution,
verification, and reconciliation. A provider proposal is never approval or
WRITE authorization.

### 4.3 Cross-Product Orchestration

A future request may need multiple Product Coordinators. The provider may
propose a high-level dependency graph, but each node must resolve to one exact
registered coordinator and retain its own authority, checkpoint, replay, and
result contracts. This amendment does not authorize a scenario-specific
mega-coordinator or a model-generated executable graph.

## 5. Compatibility And Deprecation Boundary

The shared WorkIntent, AgentContext, AgentPlan, validation, compiler,
RuntimeJob, dispatcher, worker, executor, wait/event/resume, and result
publication components remain canonical platform runtime.

New governed business WRITE behavior SHALL NOT be added to the generic direct
provider-plan path. That path remains available for IA interpretation,
delegation, exploratory/read-only work, and capabilities not yet productized.
An exact registered Product capability cannot silently fall back to direct
provider-plan execution when its coordinator or required proposal dependency
is unavailable.

Chat/RAG compatibility retirement is a separate decision and is not
authorized by this amendment.

## 6. Implementation Slices

### CP-M1-E2E-FX-01B.6B.5A.3A.1: Proposal Contract And Planning Policy

- define provider-neutral ProductPlanningProposal and registration policy;
- reuse semantic candidate storage without a migration;
- bind proposal identity into coordinator registration and activation hashes;
- preserve existing deterministic-only and generic planning compatibility.

### CP-M1-E2E-FX-01B.6B.5A.3A.2: Provider Proposal Admission And Router Wiring

- generate proposal evidence before Product preparation when policy requires;
- persist proposal payload and evidence without saving an AgentPlan;
- pass only immutable proposal reference/hash into coordinator preparation;
- reject product capability fallback and semantic drift fail closed.

### CP-M1-E2E-FX-01B.6B.5A.3A.3: Replay, Failure, And Compatibility Gate

- prove no provider recall on replay, restart, or approval redelivery;
- prove required, optional, and deterministic-only policies;
- prove malformed, low-confidence, authority-bearing, and drifted proposals
  cause zero mutation;
- prove ordinary IA, delegation, and non-product planning remain compatible;
- record whether live provider acceptance is deferred to 01B.7.

Only after these Slices close may `.5A.4` activate an installed Product
Coordinator registration.

## 7. Verification Matrix

```text
deterministic-only Product route invokes no provider PLAN        = PASS
optional Product route records admitted proposal or named fallback = PASS
required Product route cannot start without admitted proposal    = PASS
proposal is semantic evidence, never AgentPlan                   = PASS
provider authority/private field injection                       = DENIED
unknown/drifted capability or proposal contract                  = DENIED
same execution replay reuses exact proposal                      = PASS
restart and approval ACK loss do not recall provider             = PASS
READY materializer remains final execution-plan authority        = PASS
registered Product capability cannot fall through direct PLAN    = PASS
ordinary non-product direct planning remains compatible          = PASS
new queue, worker, executor, or migration                         = 0
fixed tenant, Project, amount, operation, or scenario value       = 0
```

## 8. Stop Conditions

Implementation stops for an explicit decision if:

1. Product proposal evidence cannot reuse existing semantic-candidate storage
   without corrupting immutable AgentPlan identity;
2. coordinator registration cannot bind planning policy without an
   incompatible registry migration;
3. proposal generation requires raw authority or private owner-service data;
4. replay or restart would invoke the provider again;
5. product capability failure still falls through to direct provider PLAN;
6. final materialization needs an unvalidated provider-generated tool input;
7. a scenario, tenant, or M1-specific branch enters generic planning code; or
8. provider admission cannot preserve the existing calibration and provenance
   contract.

## 9. Closure Rule

This amendment closes when provider planning is available as admitted,
immutable, non-authoritative Product proposal evidence while deterministic
Product preparation and final plan materialization remain the only execution
authority. Closure does not require every Product operation to call a model;
it requires every coordinator to declare and enforce its exact policy.

After closure, `.5A.4` may bind the policy, proposal contract, coordinator,
authority source, materializer, Skill locks, runtime handlers, and rollback
receipt into one immutable activation lock. `.5A.5` and resumed `01B.7` must
exercise the same installed composition and cannot inject a proposal from a
smoke runner or fixture.
