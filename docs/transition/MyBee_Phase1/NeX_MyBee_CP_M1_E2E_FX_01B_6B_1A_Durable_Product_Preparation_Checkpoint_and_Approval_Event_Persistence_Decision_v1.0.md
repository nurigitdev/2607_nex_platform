# NeX MyBee CP-M1-E2E-FX-01B.6B.1A: Durable Product Preparation Checkpoint and Approval Event Persistence Decision v1.0

## 1. Status And Authority

- Decision date: 2026-11-17
- Status: DESIGN_CLOSED_IMPLEMENTATION_REQUIRED
- Repository: nurigitdev/2607_nex_platform
- Branch: codex/mybee-phase1-implementation
- Predecessor: CP-M1-E2E-FX-01B.6B.1
- Parent amendment:
  `NeX_MyBee_CP_M1_E2E_FX_01B_6B_Installed_M1_Preparation_and_Deterministic_Plan_Activation_Closure_v1.0.md`
- Successor: CP-M1-E2E-FX-01B.6B.2
- Runtime code changes by this document: none
- Database migration executed by this document: none
- Migration authorized for the successor: one bounded NeX-AE migration
- Remote provider dependency: none

CP-M1-E2E-FX-01B.6B.1 proved that the current executable-step wait and
WorkResult/NSL event shapes cannot store pre-plan product preparation without
semantic overloading. This decision closes that stop condition without
creating a second wait engine, event inbox, resume queue, or product-specific
worker.

The selected architecture is:

```text
generalize the existing wait/inbox/RuntimeJob resume mechanics
  + retain typed WorkResult and NSL authority semantics
  + add immutable Product Preparation checkpoints
  + add typed Product Preparation bindings
  + route every resume through the existing Agent Runtime
```

The common lifecycle is generalized once. Domain authority remains typed and
fail-closed.

## 2. Source-Backed Entry Findings

### 2.1 Existing Common Mechanics

The repository already owns reusable mechanics:

| Existing structure | Reusable responsibility |
| --- | --- |
| `ae_wait_registration` | durable wait identity, state, matched event, resume job, and replay cursor |
| `ae_external_event_inbox` | event identity/hash, receive/match/reject outcome, and exact redelivery |
| `ae_runtime_job` | lease, retry, deduplication, attempt history, and `RESUME_EXECUTION` delivery |
| Agent Runtime worker | installed process, claim lifecycle, retry, and restart recovery |

These mechanics must not be copied into Product Preparation tables or a new
daemon.

### 2.2 Existing Domain Coupling

The reusable structures are currently constrained by earlier domains:

- `ae_wait_registration.executable_step_id` is mandatory and references an
  existing ExecutableStep;
- wait type is limited to `WORK_RESULT` or `NSL_APPROVAL`;
- `NSL_APPROVAL` columns require NSL execution, business operation, approval
  request, and checkpoint version lineage;
- `ae_external_event_inbox` accepts only `WORK_RESULT_SUBMITTED` or
  `NSL_APPROVAL_DECIDED`;
- event-shape constraints contain WorkResult and NSL-specific columns; and
- runtime code requires `RESUME_EXECUTION` to carry both a wait ID and an
  ExecutableStep ID.

These constraints are valid for their existing paths. They are not a reason
to create duplicate Product Preparation infrastructure, and they must not be
weakened into untyped JSON.

## 3. Normative Architecture Decision

### 3.1 Generic Envelope, Typed Binding

The platform SHALL use this separation:

```text
generic envelope
  = identity + lifecycle + matching + replay + resume delivery

typed binding
  = domain authority + lineage + domain validation + handler selection
```

`ae_wait_registration`, `ae_external_event_inbox`, and `ae_runtime_job` remain
the single common mechanics. WorkResult, NSL Approval, and Product
Preparation use typed bindings and validators over those mechanics.

The implementation SHALL NOT create:

- `ae_product_prep_wait` as a second wait state machine;
- `ae_product_prep_event_inbox` as a second event state machine;
- a Product Preparation job queue;
- an M1 resume daemon; or
- an M1 condition in the generic worker.

### 3.2 Product-Specific Durable State

Product Preparation has one state that does not exist today: an immutable,
pre-plan preparation checkpoint. A dedicated append-only checkpoint is
therefore required and is not considered duplicate infrastructure.

The successor migration may add only these product-specific structures:

1. `ae_product_prep_checkpoint`
2. `ae_product_prep_wait_binding`
3. `ae_product_prep_event_binding`

The checkpoint stores immutable preparation history. The bindings attach
typed Product Preparation semantics to the shared wait and event envelopes.
They do not own lifecycle state, ACK state, retry state, or RuntimeJob state.

## 4. Generalized Wait Contract

### 4.1 Resume Target

`ae_wait_registration` SHALL gain a required `resume_target_kind` with this
initial vocabulary:

```text
EXECUTABLE_STEP
PRODUCT_COORDINATOR
```

All existing rows are backfilled as `EXECUTABLE_STEP` before the column is
made non-null.

The shape rules are:

| Target | ExecutableStep | Typed binding |
| --- | --- | --- |
| `EXECUTABLE_STEP` | required | existing WorkResult or NSL lineage |
| `PRODUCT_COORDINATOR` | null | required Product Preparation wait binding |

`executable_step_id` becomes nullable only for `PRODUCT_COORDINATOR`. Existing
WorkResult and NSL rows remain constrained to an existing ExecutableStep.

### 4.2 Wait Type And Contract Reference

The admitted wait types become:

```text
WORK_RESULT
NSL_APPROVAL
PRODUCT_PREPARATION
```

The existing `result_contract_ref` name is not general enough for new writes.
The migration SHALL add `wait_contract_ref`, backfill it from
`result_contract_ref`, and preserve the old column for compatibility.

Rules:

- existing WorkResult and NSL writers continue to populate their current
  fields during the compatibility period;
- `wait_contract_ref` is authoritative for generalized code;
- Product Preparation does not write a fake result contract;
- exact replay requires the same wait type, target kind, external reference,
  contract reference, and typed binding hash; and
- a conflicting replay is rejected before any state mutation.

### 4.3 Shared Wait State Machine

The existing state vocabulary remains the single lifecycle:

```text
PENDING
  -> SATISFIED
  -> RESUME_QUEUED
  -> CONSUMED

PENDING -> CANCELLED
```

Product Preparation cannot introduce parallel status columns that duplicate
this lifecycle. Its checkpoint stage is business progress, not delivery
state.

## 5. Generalized Event Inbox Contract

### 5.1 Shared Event Envelope

`ae_external_event_inbox` remains the only external resume-event inbox. Its
common columns continue to own:

- tenant and event identity;
- event type and semantic hash;
- external reference;
- bounded event projection;
- `RECEIVED`, `MATCHED`, or `REJECTED` outcome;
- rejection reason;
- receive and process timestamps; and
- exact redelivery behavior.

The migration SHALL add an `event_family` discriminator:

```text
WORK_RESULT
NSL_APPROVAL
PRODUCT_PREPARATION
```

Existing rows are backfilled from event type. Product Preparation events use
an admitted product event type and a required
`ae_product_prep_event_binding` row. They do not populate WorkResult or NSL
columns.

### 5.2 Product Event Semantics

The first Product Preparation event types are:

```text
BUSINESS_APPROVAL_CHANGED
ACCOUNTING_APPROVAL_CHANGED
```

The word `CHANGED` is intentional. An event wakes the coordinator but does
not prove approval. The resume handler must reload fresh authority from the
owner service before creating the next checkpoint.

The event binding contains only bounded lineage:

- wait ID;
- expected checkpoint ID and hash;
- coordinator ID, version, and registration hash;
- expected authority kind and external authority reference;
- AgentExecution and WorkIntent identity; and
- binding semantic hash.

Private document, voucher, accounting, or user content remains with its owner
service and is not copied into the inbox or binding.

### 5.3 ACK-Loss And Redelivery

The existing inbox and wait states define ACK-loss convergence:

1. insert or exact-replay the event envelope;
2. resolve the pending wait and typed binding;
3. atomically mark the event `MATCHED`, mark the wait `SATISFIED`, and enqueue
   one resume RuntimeJob;
4. mark the wait `RESUME_QUEUED` with the exact RuntimeJob ID;
5. after durable coordinator transition, mark the wait `CONSUMED`; and
6. on redelivery, return the existing event, wait, job, and resulting
   checkpoint identity.

A changed event hash, checkpoint hash, authority reference, or coordinator
registration is a conflict with zero mutation.

## 6. RuntimeJob Resume Generalization

### 6.1 Retain `RESUME_EXECUTION`

No new Product Preparation job type is authorized. `RESUME_EXECUTION` means
resume an AgentExecution from a durable wait. It is generalized so an
ExecutableStep is required only when the loaded wait has
`resume_target_kind = EXECUTABLE_STEP`.

For `PRODUCT_COORDINATOR`, the RuntimeJob carries only references:

- wait ID;
- matched event ID;
- expected checkpoint ID and hash;
- coordinator registration identity; and
- dispatch contract version.

RuntimeJob payload is transport metadata, not checkpoint or approval
authority. The worker must load the wait, typed binding, checkpoint, and fresh
owner authority before transition.

### 6.2 Registry-Based Routing

The installed worker routes resume work by `resume_target_kind` through a
handler registry:

```text
EXECUTABLE_STEP      -> existing step resume handler
PRODUCT_COORDINATOR  -> generic product coordinator resume handler
```

The product handler resolves the immutable coordinator registration from the
checkpoint and binding. It does not branch on M1, tenant, prompt text,
Project count, amount, currency, or scenario name.

## 7. Immutable Product Preparation Checkpoint

### 7.1 Required Identity

`ae_product_prep_checkpoint` is append-only and SHALL include:

- checkpoint ID, schema version, and checkpoint version;
- preceding checkpoint ID and hash;
- tenant and authenticated requester;
- AgentExecution, WorkIntent revision/hash, and AgentContext generation/hash;
- business context hash;
- capability ID, version, release, and registration hash;
- coordinator ID, version, and registration hash;
- preparation adapter and materializer source identity;
- stage and stage kind;
- bounded owner-service authority references;
- idempotency, correlation, and causation identity;
- canonical checkpoint projection; and
- semantic checkpoint hash.

The checkpoint contains no raw prompt, document, voucher, payroll, account,
or approval content.

### 7.2 Stage And Version Rules

Stage names are validated against the immutable coordinator registration,
not a hardcoded M1 database check. Stage kind uses the generic vocabulary:

```text
INITIAL
WAITING
READY
TERMINAL
```

Checkpoint rows are immutable. A transition appends version `N + 1` and
references version `N`. The repository serializes one coordinator lineage per
AgentExecution and rejects gaps, forks, overwrite, delete, and altered exact
replay.

The M1 v1 progression is registered as:

```text
PREPARATION_PENDING
  -> WAITING_BUSINESS_APPROVAL
  -> WAITING_ACCOUNTING_APPROVAL
  -> READY_FOR_D04

any admitted non-terminal stage
  -> PREPARATION_FAILED | PREPARATION_CANCELLED
```

## 8. Typed Product Preparation Bindings

### 8.1 Wait Binding

`ae_product_prep_wait_binding` is a one-to-one typed extension of a shared
wait. It SHALL bind:

- tenant and wait ID;
- checkpoint ID and hash;
- coordinator registration identity;
- expected event type and authority kind;
- external authority reference;
- AgentExecution and WorkIntent identity; and
- binding semantic hash.

It may reference only a `PRODUCT_PREPARATION` wait whose target is
`PRODUCT_COORDINATOR`.

### 8.2 Event Binding

`ae_product_prep_event_binding` is a one-to-one typed extension of a shared
event envelope. It SHALL bind:

- tenant and event ID;
- wait ID;
- expected checkpoint ID and hash;
- coordinator registration identity;
- authority kind and notification reference;
- AgentExecution and WorkIntent identity; and
- binding semantic hash.

The binding is a notification lineage record. It is not approval proof.

## 9. Existing WorkResult And NSL Compatibility

This decision authorizes incremental generalization, not a big-bang rewrite.

The successor SHALL:

1. backfill existing waits and events before adding non-null generalized
   discriminators;
2. preserve current WorkResult and NSL columns, constraints, APIs, and event
   handlers;
3. keep existing WorkResult/NSL rows bound to `EXECUTABLE_STEP`;
4. run all P7 and P8 wait, event, resume, ACK-loss, and PostgreSQL regression;
5. add Product Preparation through typed extension tables; and
6. defer normalization of legacy WorkResult/NSL-specific columns into their
   own binding tables to a later controlled amendment.

The compatibility period may retain duplicated projections between old typed
columns and the new generalized discriminator. They must agree by database
constraint or repository validation. Product Preparation cannot use the old
typed columns.

## 10. AgentPlan And Registration Completion

### 10.1 Plan Version Policy

Provider PLAN output remains semantic evidence only. It is not persisted as
an executable financial AgentPlan.

The final deterministic plan created from `READY_FOR_D04` is AgentPlan
version `1`. If an AgentPlan already exists for that execution, materializing
the M1 plan fails closed with zero mutation. Overwrite and silent version `2`
fallback are prohibited.

Future staged or multi-plan execution requires another explicit amendment.

### 10.2 Coordinator Registration Fields

Before M1 activation, the coordinator registration from 6B.1 SHALL add and
hash-bind:

- checkpoint schema version;
- replay policy;
- supported executor kinds; and
- installed Skill bundle locks.

M1 remains `CONTRACT_ONLY` until these fields, the generalized persistence,
and the protected PostgreSQL Gate are complete.

## 11. Authorized Migration Boundary

The successor may create one NeX-AE migration after current migration `2516`.
The recommended identity is:

```text
2517_ae_product_preparation_resume
```

The migration may:

- generalize `ae_wait_registration` as specified;
- generalize `ae_external_event_inbox` as specified;
- create `ae_product_prep_checkpoint`;
- create `ae_product_prep_wait_binding`;
- create `ae_product_prep_event_binding`; and
- add indexes, foreign keys, checks, and immutable guards required by this
  decision.

The migration may not:

- create or change WC, OA, EOS, or WA tables;
- add a second wait, inbox, job queue, or worker;
- remove existing WorkResult/NSL columns or event types;
- store raw private business content;
- weaken existing tenant or executable-step integrity;
- add a new RuntimeJob table or Product-specific job type; or
- activate M1 before migration and compatibility tests pass.

All new PostgreSQL identifiers must remain within the 63-byte identifier
limit. The selected table names are intentionally compact.

## 12. Successor Implementation Order

CP-M1-E2E-FX-01B.6B.2 SHALL proceed in this order:

1. generalize wait and event envelopes with compatibility backfill;
2. generalize `RESUME_EXECUTION` validation and handler routing;
3. add immutable checkpoint and typed binding repositories;
4. add checkpoint schema/replay/executor/Skill locks to the coordinator
   registration;
5. activate M1 begin and both owner-authority resume transitions;
6. prove exact replay, restart, out-of-order denial, and ACK-loss convergence;
7. run actual AE/WC/OA/EOS PostgreSQL protected smoke; and
8. change M1 activation from `CONTRACT_ONLY` only after all checks pass.

No remote generation, embedding, or reranker provider is required for this
focused implementation. Live generation remains owned by the resumed
CP-M1-E2E-FX-01B.7 Gate.

## 13. Acceptance Matrix

The successor Gate must prove:

```text
one shared wait state machine                              = PASS
one shared external event inbox                           = PASS
one shared RuntimeJob/attempt queue                        = PASS
existing WorkResult resume regression                     = PASS
existing NSL approval resume regression                   = PASS
existing ExecutableStep resume requires step              = PASS
Product Coordinator resume rejects step binding           = PASS
checkpoint append-only version chain                      = PASS
Product wait/event typed binding                          = PASS
fresh owner authority reload                              = PASS
event hash conflict                                       = zero mutation
stale or out-of-order event                               = denied
ACK loss and redelivery                                   = exact replay
process restart at each wait                              = convergent
cross-tenant/requester/coordinator drift                   = denied
provider PLAN as financial AgentPlan                      = 0
duplicate wait/event/job/checkpoint/AgentPlan              = 0
new Product-specific inbox, queue, daemon, or worker       = 0
fixture or fixed M1 business values in generic runtime     = 0
```

## 14. Stop Conditions

Implementation stops if:

1. compatibility requires deleting or reinterpreting existing WorkResult or
   NSL records;
2. a Product Preparation path needs a second lifecycle state machine;
3. `RESUME_EXECUTION` cannot route by persisted wait target without an M1
   branch;
4. a checkpoint or binding would contain raw private business content;
5. the database cannot enforce target-specific ExecutableStep rules;
6. exact event redelivery cannot return the same wait, job, and checkpoint;
7. current AgentPlan version `1` is already occupied; or
8. actual PostgreSQL regression exposes existing wait/inbox semantic drift.

## 15. Closure Decision

CP-M1-E2E-FX-01B.6B.1A is design-closed with the following decision:

> Existing wait, inbox, and RuntimeJob resume mechanics become the shared
> Agent Runtime primitive. Product Preparation adds immutable checkpoint
> history and typed bindings only. Existing WorkResult and NSL behavior is
> preserved and generalized incrementally.

This decision authorizes CP-M1-E2E-FX-01B.6B.2 to implement the bounded AE
migration and runtime generalization. It does not itself activate M1 or admit
CP-M1-E2E-FX-01B.7.
