# P6-CA01A - Pre-Implementation Design Consistency Closure v1.0

**Status:** PRE-IMPLEMENTATION DESIGN CLOSURE
**Phase:** P6 - NSL READ Integration
**Observed date:** 2026-10-14
**Implementation status:** NOT STARTED BY THIS DOCUMENT

---

## 1. Purpose

P6-CA01A closes internal inconsistencies found while reviewing the P6 v1.0
design set before source-backed P6-CA01 contract extraction begins.

This closure fixes:

1. the P6 entry sequence;
2. `NSLExecutionId` allocation and semantic ownership language;
3. the P5-to-P6 `StepResult` contract version decision;
4. the version-neutral P6-S5 name;
5. worker capability and atomic claim eligibility;
6. dispatcher leadership, fairness, and backpressure boundaries;
7. deterministic timeline reconstruction limits; and
8. the source availability gate for P6-CA01.

This document is a design closure. It does not implement NSL integration,
create a migration, modify Frozen contracts, or claim that P6-CA01 is closed.

---

## 2. Inputs Reviewed

P6-CA01A reviewed the following P6 transition documents:

```text
README.md
P6_Pre_Architecture_Decision_Agent_Runtime_Worker_Dispatch_Replay_Timeline_LOCAL_SKILL_v1.0.md
P6_Architecture_Decisions_v1.0.md
P6_NSL_v0.1_to_v0.2_READ_Compatibility_Matrix_v1.0.md
P6_NSL_READ_Integration_SRS_v1.0.md
P6_Scope_Review_v1.0.md
P6_Issue_Register_v1.0.md
P6_Agent_NSL_READ_Integration_Traceability_v1.0.md
P6_CA01_v0.1_AsBuilt_to_v0.2_READ_Contract_Closure_Plan_v1.0.md
P6_Source_Audit_and_Implementation_Plan_v1.0.md
P6_Source_Baseline_Record_v1.0.md
```

Relevant P4/P5 implementation and transition records were also inspected,
including the current AE `RuntimeJob`, multi-step engine, executor registry,
and P5 `StepResult` rules.

---

## 3. Normative Precedence

This document resolves ambiguity only inside the P6 transition document set.

The precedence order is:

```text
1. Frozen Agent v2.1 / NSL v0.2 contracts
2. explicit source-backed P6-CA01 closure outputs
3. this P6-CA01A consistency closure
4. other P6 v1.0 transition documents
5. historical P4/P5 transition documents
```

P6-CA01 may refine a CA01A implementation detail only when exact Frozen or
NSL v0.1 source evidence requires it. Such a refinement must be explicit,
traceable, and must not silently rewrite this record.

---

## 4. Scope Boundary Reconfirmed

P6 remains **NSL READ Integration**.

```text
current executable backend = NSL v0.1
AE-facing target contract  = Frozen NSL v0.2 READ-compatible subset
initial executor kind       = LOCAL_SKILL
```

P6 includes:

- a continuously running AE Runtime worker;
- tenant-aware dispatch and bounded concurrency;
- exact Skill/package resolution and verification;
- canonical `SkillExecutionRequest` construction;
- a version-specific backend adapter;
- stable NSL and business-operation identities;
- conservative result mapping; and
- a complete, deterministic execution timeline projection.

P6 excludes:

- NSL WRITE;
- approval and WRITE checkpoint semantics;
- commit/verification state;
- WC execution;
- CA, PA, or EA execution expansion;
- arbitrary operator replay;
- a second Agent Runtime hierarchy; and
- replacement of AE RuntimeJob with the shared service JobQueue.

---

## 5. CA01A-DEC-01 - Canonical P6 Entry Sequence

The canonical P6 sequence is strictly ordered:

```text
P6 document-set review
-> P6-CA01A design consistency closure
-> P6-CA01 source-backed contract closure
-> P6-S0 AE Runtime worker foundation
-> P6-S1 tenant dispatcher and operations
-> P6-S2 Skill Artifact Gateway
-> P6-S3 request and identity binding
-> P6-S4 LOCAL_SKILL executor
-> P6-S5 NSL READ Backend Integration
-> P6-S6 result and timeline integration
-> P6-S7 READ E2E closure
```

The earlier allowance to begin P6-S0/S1 before P6-CA01 is withdrawn for this
implementation run.

Rationale:

- worker capability and claim eligibility depend on the final executor contract;
- process-isolation selection can affect worker composition;
- identity persistence affects worker restart behavior; and
- the project prioritizes contract drift prevention over speculative parallelism.

No P6 feature Slice begins before P6-CA01 closes.

---

## 6. CA01A-DEC-02 - NSLExecutionId Allocation and Ownership

The earlier phrases "P6-owned/Integration-owned" and "NSL Runtime owns
NSLExecutionId semantics" describe different responsibilities and are not
mutually exclusive.

The canonical responsibility split is:

### AE Integration owns

- allocating `NSLExecutionId` before backend invocation;
- durably binding it to the logical LOCAL_SKILL step;
- returning the same ID after retry, lease reclaim, or worker restart;
- exposing it in AE timeline and result lineage; and
- mapping it to the selected backend adapter request.

### NSL Runtime owns

- validating and consuming the supplied execution identity;
- the execution lifecycle associated with that identity;
- deterministic READ execution semantics;
- runtime limits, tool invocation, and evidence; and
- future NEW/WAIT/RESUME meaning inside one logical NSL execution.

### Initial v0.1 mapping

```text
P6 NSLExecutionId
-> NSL v0.1 SkillExecutionJob.execution_id
```

`AgentExecutionId`, `ExecutableStepId`, `NSLExecutionId`, and
`BusinessOperationId` remain distinct identities.

---

## 7. CA01A-DEC-03 - Identity Persistence Before Side Effect

For one P6 LOCAL_SKILL READ step, AE SHALL create or load a durable execution
binding before calling the NSL backend.

The logical authority is:

```text
AE-owned NSLStepExecutionBinding
```

The physical implementation may use `ae_nsl_step_execution` or an equivalent
short AE-owned table name selected during implementation.

For the P6 READ scope there is exactly one logical NSL execution binding per
LOCAL_SKILL executable step:

```text
UNIQUE (tenant_id, executable_step_id)
```

The binding contains at minimum:

```text
tenant_id
agent_execution_id
executable_plan_id
executable_step_id
nsl_execution_id
business_operation_id
skill_id
exact_skill_version
skill_semantic_hash
verified_artifact_ref/hash
request_hash
backend_profile
state
result_summary_ref/hash
created_at
updated_at
```

The allocation transaction must commit before the first external/backend call.

A technical retry reuses the binding. A semantic replan that creates a new
ExecutableStep receives new NSL and business-operation identities.

P6 does not support multiple logical NSL executions for one ExecutableStep.
That expansion requires a later versioned contract with an invocation ordinal
or equivalent identity.

---

## 8. CA01A-DEC-04 - BusinessOperationId READ Semantics

Every P6 NSL READ invocation carries a stable non-null `BusinessOperationId`.

For READ it is:

> An Agent/Platform-owned semantic operation and correlation identity.

It is not:

- WRITE authority;
- an idempotency key for an external mutation;
- a commit identity; or
- evidence that a side effect occurred.

For one logical LOCAL_SKILL READ execution:

```text
business_operation_id = stable across technical retry/restart
operation_fingerprint = null
```

AE allocates and persists `BusinessOperationId` in the same pre-invocation
binding transaction as `NSLExecutionId`.

---

## 9. CA01A-DEC-05 - StepResult Contract Version 1.2

The P6 `StepResult` semantic contract version is fixed as **1.2**.

### Historical P5 v1.1

Persisted P5 v1.1 results remain immutable and retain:

```text
business_operation_id = null
operation_fingerprint = null
```

They are not reinterpreted or backfilled merely because P6 is deployed.

### P6 v1.2 conditional rule

```text
non-NSL executor:
  business_operation_id = null
  operation_fingerprint = null

LOCAL_SKILL READ executor:
  business_operation_id = required stable non-null
  operation_fingerprint = null
```

The condition is based on the canonical executor/invocation kind, not on
whether a caller happened to provide a value.

Readers introduced by P6 SHALL accept supported historical v1.1 and current
v1.2 records. Writers SHALL emit only the version they explicitly implement.

P6-CA01 must still produce and validate the exact machine-readable v1.2 schema,
field names, enums, and adapter rules. CA01A fixes the semantic version decision;
it does not substitute for that schema.

---

## 10. CA01A-DEC-06 - Version-Neutral P6-S5 Name

The canonical Slice name is:

```text
P6-S5: NSL READ Backend Integration
```

The name `NSL v0.2 READ Runtime Integration` is retired because it could imply
that a native NSL v0.2 runtime is already implemented.

Initial backend:

```text
V01ReadBackendAdapter -> current NSL v0.1 runtime
```

Future backend replacement must not change AE identities or the canonical
P6 request/result contracts.

---

## 11. CA01A-DEC-07 - Initial Worker Topology

P6 begins with one homogeneous AE Runtime worker pool for the deployed profile.

Every worker in that pool SHALL:

- declare its supported executor kinds at startup;
- include `LOCAL_SKILL` before claiming a LOCAL_SKILL RuntimeJob;
- fail startup if a configured executor has no implementation;
- use the same bounded deployment capability profile; and
- refuse unknown executor kinds fail-closed.

P6 may retain existing non-NSL executors in the same worker registry. It does
not create a second RuntimeJob hierarchy or a second worker authority.

Heterogeneous executor-specific worker pools are outside initial P6 closure.
They require a later routing contract if introduced.

---

## 12. CA01A-DEC-08 - Capability-Aware Atomic Claim

The dispatcher SHALL never intentionally lease work to a worker that cannot
execute the referenced step.

All P5 multi-step RuntimeJobs already identify an `executable_step_id`.
P6-S1 SHALL extend claim candidate selection so that it checks the associated
canonical `ExecutableStep.executor_kind` against the worker's declared
capability set before the claim update succeeds.

Required property:

```text
eligible runnable job selection
+ executor capability filter
+ lease compare-and-set update
= one claim transaction
```

A separate preflight query followed by an unfiltered claim is insufficient.

If a legacy malformed job has no resolvable step or executor kind, it is not
eligible for normal execution. It must remain observable and follow an explicit
reconciliation/dead-letter path.

---

## 13. CA01A-DEC-09 - Dispatcher Leadership and Fairness

The initial deployment profile has one active dispatcher leader per AE Runtime
queue. Additional processes, if configured, are standby and must not create an
independent fairness authority.

Leadership SHALL be protected by a database-backed lease, advisory lock, or an
equivalent single-active mechanism selected in P6-S1.

One dispatch round is defined as:

1. discover a bounded snapshot of runnable tenants;
2. order tenants by oldest runnable work and stable `tenant_id` tie-break;
3. visit each eligible tenant at most once in that round;
4. claim at most the configured per-tenant amount;
5. stop when the global capacity bound is reached; and
6. rebuild the next round from canonical database state.

The dispatcher cursor is not an in-memory business authority. Restart may
rebuild a round from persisted queue state without losing correctness.

Fairness acceptance must prove that a continuously busy tenant cannot starve
another runnable tenant under configured bounds.

---

## 14. CA01A-DEC-10 - Backpressure and Admission Boundary

P6 distinguishes execution admission from work execution.

The required limits are:

```text
global active claims
per-tenant active claims
dispatch batch size
worker concurrency
maximum runnable queue depth
maximum delayed/dead-letter retention according to policy
```

When execution capacity is exhausted:

- existing durable work remains queued;
- the dispatcher does not over-claim;
- retry scheduling remains bounded;
- overload is observable with bounded-cardinality metrics; and
- API admission follows an explicit configured reject-or-delay policy.

P6-S1 must define the exact rejection/error code and delayed-admission behavior.
Raw prompts, user content, execution IDs, and principal IDs are not generic
metric labels.

---

## 15. CA01A-DEC-11 - Timeline Determinism

The P6 AgentExecution timeline is a protected read projection over canonical
records. It is not an independently mutable event SoR.

Events are ordered by this deterministic key:

```text
(event_time, phase_order, source_type_order, stable_source_id)
```

After sorting, the projection assigns a one-based `sequence` value.

`phase_order` and `source_type_order` are versioned projection constants and
must be covered by regression tests. They resolve equal timestamps; they do
not alter persisted business state.

Timeline generation SHALL be deterministic for the same canonical snapshot.

---

## 16. CA01A-DEC-12 - Timeline Reconstruction Limits

The phrase "complete execution timeline" means complete over the canonical
records and evidence retained by P6. It does not authorize invented history.

Rules:

- emit `state_before` only when canonical history proves it;
- emit `state_after` only when the source record or transition proves it;
- leave an unavailable optional field null rather than infer it;
- identify projection gaps explicitly in operational metadata;
- never copy raw prompt, response, document content, secret, credential,
  provider endpoint, or database URL into the timeline; and
- retain stable evidence references instead of copying the NSL audit journal.

P6-S6 source audit must verify whether existing records can represent every
minimum event. A new timeline SoR table is prohibited unless that audit proves
a specific required transition cannot be represented by existing immutable
records or bounded evidence.

---

## 17. CA01A-DEC-13 - P6-CA01 Source Availability Gate

At CA01A review time:

```text
Platform repository: available
Platform HEAD: e112606eedbd8f0fb8fac0aab5ddbb52d2f40c7e
Recorded Platform baseline match: yes

NSL repository expected path: /home/tprover/2608_nsl
NSL repository locally available: no
Recorded NSL baseline: 803f22aadc3946a48b05472c80b60fe11d9d9554
Recorded NSL baseline verified during CA01A: no
```

P6-CA01 cannot close until the NSL repository is available and the actual
checkout SHA is recorded.

P6-CA01 SHALL inspect the exact source rather than relying only on P6 design
documents for:

- `ExecutionStatus` enumeration;
- request/result API shape;
- NSP verification and trust evidence;
- process-isolation behavior;
- timeout/crash containment;
- audit/evidence references; and
- the Golden READ fixture path.

If the available NSL SHA differs from the recorded baseline, CA01 records the
drift before creating transition schemas.

---

## 18. Issues Closed by CA01A

| Closure item | CA01A result | Follow-up |
|---|---|---|
| Conflicting entry sequence | Sequential CA01A -> CA01 -> S0..S7 fixed | Update cross-references when P6 docs are consolidated |
| NSLExecutionId ownership wording | AE allocates/persists; NSL owns execution lifecycle semantics | CA01 verifies v0.1 adapter mapping |
| StepResult version ambiguity | Semantic contract v1.2 fixed | CA01 creates machine schema |
| P6-S5 version claim | Version-neutral Slice name fixed | Use consistently in plans and commits |
| Worker capability ambiguity | Homogeneous initial pool and fail-closed declaration fixed | S0 implements startup check |
| Unsupported claim risk | Capability filter must be in claim transaction | S1 implements/tests atomic query |
| Dispatcher authority | Single active DB-protected leader fixed | S1 selects lease/lock mechanism |
| Fairness after restart | Rounds rebuild from durable queue state | S1 proves bounded fairness |
| Timeline tie handling | Deterministic ordering key fixed | S6 versions/tests projection |
| Timeline overclaim | No invented history; optional unknowns remain null | S6 audits canonical sources |
| Source readiness | NSL source required before CA01 closure | Prepare/checkout repository |

---

## 19. Items Intentionally Left for P6-CA01

CA01A does not decide facts that require the exact NSL v0.1 source.

P6-CA01 remains responsible for:

1. refreshed Platform and NSL SHAs;
2. exact `SkillExecutionRequest` transition schema;
3. exact `VerifiedSkillArtifact` projection;
4. exact `NSLResultSummary` schema;
5. exact binding and StepResult v1.2 machine schemas;
6. exhaustive v0.1 status mapping;
7. bounded `AgentContext` projection schema;
8. in-process versus process-isolated production backend decision;
9. crash/timeout containment acceptance design;
10. exact Golden READ Skill/Tool fixture; and
11. complete v0.1 adapter field mapping.

No P6 Slice may infer these unresolved contracts independently.

---

## 20. Required P6-CA01 Deliverables

After source availability is satisfied, P6-CA01 shall produce at minimum:

```text
docs/transition/P6/contracts/
  p6-skill-execution-request-v1.schema.json
  p6-verified-skill-artifact-v1.schema.json
  p6-nsl-result-summary-v1.schema.json
  p6-nsl-step-execution-binding-v1.schema.json
  p6-step-result-v1.2.schema.json
```

The final names may follow repository naming conventions, but each semantic
contract must be machine-readable, versioned, validated, and traceable.

P6-CA01 also records:

- source-to-contract mapping;
- status-to-StepResult mapping;
- process profile decision;
- Golden READ fixture identity;
- compatibility and negative-test matrix; and
- remaining deferred work.

---

## 21. P6-CA01A Exit Gate

P6-CA01A is complete when this document is accepted and the following statements
are treated as binding for P6 implementation:

- P6 uses the sequential CA01A -> CA01 -> S0..S7 path;
- AE allocates and persists both P6 invocation identities before backend call;
- NSL Runtime owns execution lifecycle semantics, not AE identity allocation;
- P6 StepResult semantic contract version is 1.2;
- P6-S5 is version-neutral;
- workers declare capabilities and claims filter them atomically;
- one database-protected dispatcher leader owns each queue;
- fairness is bounded, deterministic, and restart-reconstructable;
- timeline ordering is deterministic and never fabricates missing history;
- the NSL source checkout is mandatory for CA01; and
- no P6 feature implementation is claimed by this closure.

---

## 22. Final Closure Statement

P6-CA01A closes the design-set consistency gap and establishes one safe path
into source-backed contract extraction.

The next authorized activity is:

```text
prepare and verify the NSL v0.1 source checkout
-> execute P6-CA01
-> validate transition schemas and adapter mappings
-> begin P6-S0 only after P6-CA01 closure
```

P6 remains a narrow READ integration phase. It does not widen into NSL v0.2
runtime implementation, WRITE semantics, WC, or additional Agent roles.
