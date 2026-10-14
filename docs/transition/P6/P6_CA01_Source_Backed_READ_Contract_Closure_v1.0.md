# P6-CA01 - Source-Backed NSL READ Contract Closure v1.0

**Status:** CLOSED
**Observed date:** 2026-10-14
**Scope:** NSL READ integration only
**Predecessor:** P6-CA01A Pre-Implementation Design Consistency Closure v1.0

## 1. Closure Statement

P6-CA01 inspected the exact Platform, Frozen, and NSL v0.1 baselines and
freezes the implementation-facing READ contracts required before P6-S0.

This closure does not implement a worker, migration, dispatcher, LOCAL_SKILL
executor, or NSL backend adapter. It authorizes those Slices to begin against
one source-backed contract set.

## 2. Exact Source Baselines

```text
Platform repository: nurigitdev/2607_nex_platform
Platform branch: transition/p4-agent-runtime-foundation
Platform reviewed HEAD: 380efb339cb9e3119a32e9229cbcb5f0075d5f0f
Platform working tree before CA01 edits: clean

NSL repository: nurigitdev/2608_nsl
NSL reviewed HEAD: 803f22aadc3946a48b05472c80b60fe11d9d9554
NSL tag: v0.1
Expected baseline match: yes
NSL working tree: clean
```

The checkout paths used during review are environment evidence, not runtime
architecture requirements.

## 3. Normative Inputs Reviewed

Frozen inputs:

- Agent v2.1 to NSL v0.2 Integration Contract v1.0;
- Frozen `SkillExecutionRequest v2.1` schema;
- Frozen `VerifiedSkillArtifact v2.1` and trust schemas;
- Frozen `NSLResultSummary v2.1` schema and Python protocol;
- NSL v0.2 Runtime ExecutionContext design; and
- NSL v0.2 Runtime Python Interface/Protocol design.

NSL v0.1 source and As-Built inputs:

- `nsl/integration.py`, `worker.py`, `api/`, `runtime.py`,
  `runtime_models.py`, `tools.py`;
- `nsp.py`, `nsp_verification.py`, `nsp_signatures.py`;
- `process_isolation.py`, `audit.py`, `protected_snapshots.py`; and
- As-Built documents 25, 35, 36, and 37 required by the CA01 plan.

Platform inputs:

- `runtime_jobs.py`, `multi_step_engine.py`, `step_executors.py`;
- `step_results.py`, `planning_capabilities.py`, `executable_plans.py`;
- `plan_finalization.py`, `agent_runtime_foundation.py`; and
- migrations 2003-2006 and 2104-2106.

## 4. Machine Contract Closure

The canonical P6 transition contract set is under `contracts/`:

```text
p6-skill-execution-request-v1.schema.json
p6-verified-skill-artifact-v1.schema.json
p6-nsl-result-summary-v1.schema.json
p6-nsl-step-execution-binding-v1.schema.json
p6-step-result-v1.2.schema.json
p6-context-projection-v1.schema.json
```

All are JSON Schema Draft 2020-12, closed to unknown top-level properties,
versioned, and accompanied by a coherent Golden READ example lineage.

## 5. Identity and Cardinality Closure

| Identity | Allocator | Durable authority | Cardinality and lifecycle |
|---|---|---|---|
| AgentExecutionId | AE admission | `ae_agent_execution` | One Agent execution; 1:N executable steps |
| ExecutablePlanId | AE compiler | `ae_executable_plan` | Versioned plan for one Agent execution |
| ExecutableStepId | AE compiler | `ae_executable_step` | One canonical compiled step |
| NSLExecutionId | AE P6 integration | `NSLStepExecutionBinding` | Exactly one per `(tenant_id, executable_step_id)` in P6 |
| BusinessOperationId | AE P6 integration | same binding | Stable READ semantic/correlation identity |

AE allocates and commits NSLExecutionId and BusinessOperationId in the same
binding transaction before the first backend call. Retry, lease reclaim, and
worker restart reload both. A semantic replan creates a new ExecutableStep and
therefore new IDs.

Initial adapter mapping:

```text
P6 nsl_execution_id
-> NSL v0.1 SkillExecutionJob.execution_id
```

No other P6 identity is collapsed into the v0.1 field.

## 6. StepResult v1.2 Closure

The v1.2 schema adds canonical `executor_kind` so the identity rule is based on
the executor contract rather than caller-provided data.

```text
executor_kind = LOCAL_SKILL
  business_operation_id = required UUID
  operation_fingerprint = null

executor_kind != LOCAL_SKILL
  business_operation_id = null
  operation_fingerprint = null
```

P5 v1.1 remains immutable. P6 readers dispatch explicitly on `schema_version`
and accept supported 1.1 and 1.2 records; P6 writers do not rewrite 1.1.

## 7. Artifact and Trust Projection

NSL v0.1 `VerifiedNspPackage` supplies:

- exact manifest Skill ID/version;
- NSO semantic hash and bytes;
- package hash; and
- optional verified signature metadata with signing key ID.

It does not natively carry Frozen `publisher_id`, `verified_at`, trust policy,
or governance decision. The AE Skill Artifact Gateway therefore adds those
governed catalog/admission facts without reimplementing cryptography.

P6 persists the bounded `VerifiedSkillArtifact` projection and hashes it. Raw
signature bytes, package verification journal, and protected package content
remain behind `backend_artifact_handle`, trust evidence refs/hashes, and the
artifact-admission decision ref/hash.

For NSP v0.1, `package_id` is deterministically projected as:

```text
nsp:<lowercase package SHA-256 digest>
```

Production requires a signed package, current valid trust evidence, ACTIVE
governance, exact version, and exact semantic/package hash match.

## 8. Exhaustive v0.1 Request Adapter Mapping

| P6 request field | NSL v0.1 mapping | Durable-only / rule |
|---|---|---|
| `tenant_id` | principal tenant validation | retained in binding |
| `agent_execution_id` | none | binding only |
| `executable_plan_id` | none | binding only |
| `executable_step_id` | none | binding and RuntimeJob join |
| `nsl_execution_id` | `SkillExecutionJob.execution_id` | exact |
| `business_operation_id` | no v0.1 field | binding/result lineage only |
| `skill_id` | `SkillExecutionJob.skill_id` | exact selector |
| `exact_skill_version` | `SkillExecutionJob.skill_version` | no latest substitution |
| `expected_semantic_hash` | `expected_semantic_hash` | worker rechecks after resolve |
| `runtime_contract_ref` | none | artifact/binding evidence |
| `compiled_inputs` | `StructuredInputs` | typed canonical wire |
| `input_provenance` | `InputProvenance` | exactly covers input names |
| `explicit_resource_refs` | declared projection only | not copied as arbitrary context |
| `principal_context_ref` | resolves `VerifiedPrincipalContext` | unresolved fails closed |
| `data_policy_ref` | resolves `ExplicitDataHandlingPolicy` | unresolved fails closed |
| `context_projection_ref/hash` | resolves bounded `StructuredRuntimeContext` | hash verified first |
| `correlation_id`, `causation_id` | no v0.1 job field | binding/timeline only |
| `agent_context_ref/hash` | no v0.1 job field | binding/provenance only |
| `mode=NEW` | v0.1 normal execute | RESUME unavailable in P6 |

All fields have an explicit mapping. There is no generic remainder map.

## 9. Context Projection Closure

Whole AgentContext serialization is prohibited. The P6 projection contains:

- at most 64 declared dotted runtime-context paths;
- typed compiled inputs and exact USER/CONTEXT/DEFAULT provenance;
- at most 64 explicit resource refs;
- verified principal and bounded role/scope sets;
- bounded organization/project authority metadata;
- data classification and retention policy; and
- AgentContext/projection refs and hashes.

The adapter deterministically inflates dotted paths to v0.1
`StructuredRuntimeContext`. Duplicate/overlapping paths, undeclared Skill
context paths, credential-bearing keys/values, authority supplied by prompt or
LLM output, and hash mismatch fail closed.

## 10. Exhaustive v0.1 Status Mapping

The exact NSL v0.1 `ExecutionStatus` enum has eight values.

| v0.1 status | P6 StepExecutionOutcome | StepResult | AgentExecution progression | Retry class |
|---|---|---|---|---|
| `CREATED` | `RUNNING` | none | remains `RUNNING/STEP_EXECUTION` | not terminal |
| `RUNNING` | `RUNNING` | none | remains `RUNNING/STEP_EXECUTION` | not terminal |
| `COMPLETED` | `SUCCEEDED` | `SUCCEEDED` | schedule next step or result verification | none |
| `FAILED` | `FAILED` | `FAILED` | terminal/finalization policy | policy-controlled READ retry |
| `TOOL_ERROR` | `FAILED` | `FAILED` | terminal/finalization policy | policy-controlled READ retry |
| `VALIDATION_ERROR` | `BLOCKED` | `BLOCKED` | `BLOCKED` | no technical retry |
| `LIMIT_EXCEEDED` | `FAILED` | `FAILED` | terminal/finalization policy | no automatic retry without changed limits/input |
| `CANCELLED` | `CANCELLED` | `CANCELLED` | `CANCELLED` | none |

`CREATED` or `RUNNING` in a terminal `RuntimeResultEnvelope` is a backend
protocol violation. It is recorded as adapter evidence and does not create a
false terminal StepResult.

## 11. Process Profile Decision

The P6 production profile is:

```text
NSL_V01_PROCESS_ISOLATED
```

The AE worker remains the queue/lease authority. One trusted bytes-to-bytes NSL
entrypoint runs in a spawned child through v0.1 `ProcessIsolatedRuntime`.

Initial limits:

```text
timeout_ms = 30000
max request bytes = 8 MiB
max result bytes = 8 MiB
WorkerEvidencePolicy = SNAPSHOT_REQUIRED
```

Isolation outcomes map as follows:

| Isolation status | Adapter disposition |
|---|---|
| `COMPLETED` | decode and validate canonical `RuntimeResultEnvelope` |
| `TARGET_ERROR` | terminal backend failure evidence; no raw child exception |
| `CRASHED` | terminal attempt failure; parent worker survives |
| `TIMED_OUT` | child terminated; parent worker survives |
| `PROTOCOL_ERROR` | terminal adapter/protocol failure |

All failed isolation outcomes preserve the same NSL/BusinessOperation IDs for
a policy-authorized technical retry. No child exception text becomes public.

## 12. Golden READ Fixture

Fixture `P6-GOLDEN-READ-001` uses exact NSL source commit `803f22a...`:

```text
source: examples/project_budget_check.ns
skill: FINANCE.PROJECT_BUDGET_CHECK@1.0.0
semantic hash: sha256:ba75f7b96d08f0a8bff6ff1917b127c36cf2a0c96f1d29b7dc883674a4678b56
signed package hash: sha256:9e538ec352bddc4ba4a43ac1510759c02491f74f52c50bf4f817f94c9925622e
tools: PROJECT.LIST_PARENT_PROJECTS@1.0.0, PROJECT.LIST_CHILD_PROJECTS@1.0.0
provider: deterministic checked-in success fixture
```

The selected package is deterministically compiled, built, and signed with a
test-only Ed25519 fixture profile. Production signature policy verification and
process-isolated execution both succeeded during CA01 extraction.

Expected result:

```text
status=COMPLETED, completeness=COMPLETE, check=PASS
tool_calls=2, loop_iterations=1, emitted_rows=1
budget=100000000 KRW
spent=87500000 KRW
remaining=12500000 KRW
```

The full source recipe, package digests, public key, output assertions, and
evidence policy are frozen in
`contracts/examples/p6-golden-read-fixture-v1.json`.

## 13. Worker Capability and Claim Inputs

P6-S0 worker startup freezes this profile shape:

```text
schema_version = 1.0
worker_id
supported_executor_kinds[]
supported_backend_profiles[]
max_concurrent_claims
evidence_policy
process_isolation_required
declared_at
```

Initial required values include:

```text
supported_executor_kinds contains LOCAL_SKILL
supported_backend_profiles contains NSL_V01_PROCESS_ISOLATED
evidence_policy = SNAPSHOT_REQUIRED
process_isolation_required = true
```

Atomic claim inputs are tenant, worker ID, capability set, lease seconds, and
observed time. Candidate selection must join `ae_runtime_job.executable_step_id`
to the same-tenant `ae_executable_step`, filter `executor_kind` before leasing,
and perform lease CAS in the same transaction.

Malformed jobs with null/unresolvable steps or unsupported executors are not
normal claim candidates. S1 must expose and move them through an explicit
reconciliation/dead-letter path.

Runnable tenant discovery must apply the same capability eligibility and order
by oldest runnable time then stable tenant ID. Required indexes are a runnable
job index beginning with state/run time/tenant and the existing step primary
key; S1 may refine the exact PostgreSQL index after `EXPLAIN` evidence.

Dispatcher leadership candidate is a short, observable DB lease record keyed
by queue name, with owner, fencing token, and lease expiry. A process-local
lock or cursor is not authority.

## 14. Timeline Source Matrix

| Event/evidence | Canonical source | Availability |
|---|---|---|
| execution admitted | `ae_agent_execution.received_at/created_at` | directly represented |
| current execution state/phase | `ae_agent_execution.state/phase/updated_at` | directly represented current snapshot |
| all historical execution phase transitions | no immutable transition rows | unavailable; emit projection gap |
| plan compiled | `ae_executable_plan.compiled_at` | directly represented |
| step persisted/current state | `ae_executable_step.created_at/state/updated_at` | directly represented current snapshot |
| all historical step state transitions | no immutable transition rows | unavailable; emit projection gap |
| job queued/runnable | `ae_runtime_job.created_at/run_after` | directly represented |
| claim/attempt started | `ae_runtime_job_attempt.started_at` | directly represented |
| lease expiry/final attempt outcome | attempt `ended_at/outcome/error_ref` | directly represented |
| binding/IDs allocated | P6 binding `allocated_at` | directly represented after S3 |
| canonical request bound | binding `request_bound_at/ref/hash` | directly represented after S3 |
| NSL invocation started | binding `invocation_started_at` | directly represented after S3 |
| NSL progress STARTED/RESOLVED/RUNNING | ordered v0.1 Progress evidence | directly represented when retained by S5 |
| NSL result completed | result summary `completed_at/ref/hash` | directly represented after S5 |
| StepResult terminal | `ae_step_result.started_at/completed_at/status` | directly represented |
| AgentResult created | `ae_agent_result.created_at/status/hash` | directly represented |
| delivery created/current state | `ae_result_delivery.created_at/state/updated_at` | directly represented current snapshot |

Attempt-derived lease events are unambiguous because each attempt has a unique
attempt number and outcome. Current-state timestamps do not prove every prior
state and must not be expanded into invented history.

Projection order remains:

```text
(event_time, phase_order, source_type_order, stable_source_id)
```

## 15. Negative-Test Matrix

| ID | Rejected condition |
|---|---|
| P6-CA01-N01 | unknown schema property or unsupported schema version |
| P6-CA01-N02 | collapsed/equal semantic use of Agent, Step, NSL, and BusinessOperation IDs |
| P6-CA01-N03 | retry creates new NSLExecutionId or BusinessOperationId for the same step |
| P6-CA01-N04 | missing/non-UUID BusinessOperationId for LOCAL_SKILL StepResult |
| P6-CA01-N05 | non-NSL StepResult carries BusinessOperationId or operation fingerprint |
| P6-CA01-N06 | unsigned/untrusted/inactive/semantic-mismatched artifact |
| P6-CA01-N07 | latest-version substitution or skill selector mismatch |
| P6-CA01-N08 | input provenance does not exactly cover compiled input names |
| P6-CA01-N09 | full AgentContext, raw prompt/content, credential, or untrusted authority injection |
| P6-CA01-N10 | unresolved principal/data-policy/context ref or projection hash mismatch |
| P6-CA01-N11 | terminal status converted to empty success |
| P6-CA01-N12 | CREATED/RUNNING accepted as terminal result |
| P6-CA01-N13 | isolation crash/timeout terminates or wedges the AE parent worker |
| P6-CA01-N14 | worker claims unsupported or unresolvable executor kind |
| P6-CA01-N15 | terminal binding lacks result summary ref/hash and event timestamps |
| P6-CA01-N16 | timeline fabricates unavailable state-before/state-after |
| P6-CA01-N17 | raw NSL audit journal copied into AE timeline/result |
| P6-CA01-N18 | P6 READ request contains WRITE/resume/commit fields |

## 16. Deferred Implementation Work

- S0 implements the worker process/profile validation.
- S1 implements leader lease, tenant discovery, atomic capability-aware claim,
  fairness, backpressure, and malformed-job reconciliation.
- S2 implements artifact gateway/admission persistence.
- S3 implements binding/request/context persistence and StepResult reader/writer
  version dispatch.
- S4 activates LOCAL_SKILL in capability/compiler/executor registry.
- S5 implements the process-isolated v0.1 adapter and progress/evidence bridge.
- S6 implements result mapping and deterministic timeline projection.
- S7 proves protected PostgreSQL E2E and closes NSL-AE-004/008.

NSL WRITE, approval/resume, commit state, WC, CA/PA/EA expansion, and arbitrary
replay remain outside P6.

## 17. Exit Gate Result

| Gate | Result |
|---|---|
| exact Platform/NSL SHAs recorded | PASS |
| six transition schemas validate | PASS |
| identity/cardinality fixed | PASS |
| StepResult v1.2 fixed | PASS |
| artifact/trust projection fixed | PASS |
| adapter mapping exhaustive | PASS |
| status mapping exhaustive | PASS |
| bounded context projection fixed | PASS |
| process profile selected | PASS |
| Golden READ fixture selected and executed | PASS |
| worker/claim inputs fixed | PASS |
| timeline source matrix complete | PASS |
| negative-test matrix complete | PASS |

Validation evidence:

```text
P6 CA01 focused contract tests: 16 passed
AE Slice Gate: 3485 passed, 5 protected PostgreSQL smoke tests skipped by opt-in guard
Statement coverage: 98.61% (required >= 95%)
Branch coverage: 96.82% (required >= 94%)
Repository contract validation:
  schemas=174
  examples=236
  negative_examples=204
  openapi=7
  status=PASS
```

The skipped tests are existing environment-protected PostgreSQL smoke suites;
P6-CA01 changes no database or runtime source and does not claim those smokes as
executed evidence.

P6-CA01 is closed. The next authorized implementation Slice is P6-S0.
