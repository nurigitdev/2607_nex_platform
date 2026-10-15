# P6 Transition Implementation Baseline v1.1

**Status:** P6 IMPLEMENTATION COMPLETE
**Phase:** P6 — NSL READ Integration
**Implementation Baseline:** NSL v0.1 As-Built
**Target Contract:** Frozen NSL v0.2 READ-compatible integration subset
**Predecessor:** P5 Agent Planning & Execution Foundation — IMPLEMENTATION COMPLETE

## 1. Naming

Stable SRS name:

```text
P6_NSL_READ_Integration_SRS_v1.1.md
```

```text
Current executable backend = NSL v0.1
AE-facing target contract  = Frozen NSL v0.2 READ-compatible subset
```

## 2. Canonical Entry Sequence

CA01A supersedes the v1.0 partial-parallel rule.

```text
P6 document-set review
→ P6-CA01A design consistency closure
→ P6-CA01 source-backed contract closure
→ P6-S0 AE Runtime Worker Foundation
→ P6-S1 Tenant Dispatcher / Operations
→ P6-S2 Skill Artifact Gateway
→ P6-S3 Request / Identity Binding
→ P6-S4 LOCAL_SKILL Executor
→ P6-S5 NSL READ Backend Integration
→ P6-S6 Result / Timeline Integration
→ P6-S7 E2E-01 IA READ Closure
```

**No P6 feature Slice begins before P6-CA01 closes.**

## 3. Authority

```text
Frozen Platform v2.1 / Agent v2.1 / NSL v0.2
> approved source-backed P6-CA01 outputs
> P6-CA01A Pre-Implementation Design Consistency Closure v1.0
> this P6 v1.1 consolidated transition set
> P6 v1.0 historical transition docs
> P4/P5 historical transition docs
> implementation convenience
```

## 4. Required Reading Order

1. Frozen baseline and Agent↔NSL Integration Contract
2. `P6_CA01A_Pre_Implementation_Design_Consistency_Closure_v1.0.md`
3. `P6_Pre_Architecture_Decision_Agent_Runtime_Worker_Dispatch_Replay_Timeline_LOCAL_SKILL_v1.1.md`
4. `P6_Architecture_Decisions_v1.1.md`
5. `P6_NSL_v0.1_to_v0.2_READ_Compatibility_Matrix_v1.1.md`
6. `P6_NSL_READ_Integration_SRS_v1.1.md`
7. `P6_Scope_Review_v1.1.md`
8. `P6_Issue_Register_v1.1.md`
9. `P6_Agent_NSL_READ_Integration_Traceability_v1.1.md`
10. `P6_CA01_v0.1_AsBuilt_to_v0.2_READ_Contract_Closure_Plan_v1.1.md`
11. `P6_CA01_Source_Backed_READ_Contract_Closure_v1.0.md`
12. `contracts/README.md` and the six machine-readable transition contracts
13. `P6_Source_Baseline_Record_v1.1.md`
14. current Platform P5 As-Built and exact NSL v0.1 source checkout
15. `P6_Source_Audit_and_Implementation_Plan_v1.1.md`
16. `../../slices/p6_s0_ae_runtime_worker_foundation.md`
17. `../../slices/p6_s1_db_protected_tenant_dispatcher.md`
18. `../../slices/p6_s1a_runtime_dispatch_semantic_hardening.md`
19. `../../slices/p6_s2_skill_artifact_gateway.md`
20. `../../slices/p6_s3_nsl_step_execution_binding.md`
21. `../../slices/p6_s4_local_skill_executor_activation.md`
22. `../../slices/p6_s5_nsl_read_backend_integration.md`
23. `../../slices/p6_s6_result_timeline_integration.md`

## 5. CA01A Non-Negotiable Rules

```text
AE allocates/persists:
  NSLExecutionId
  BusinessOperationId

NSL Runtime owns:
  lifecycle semantics for supplied NSLExecutionId
```

```text
one LOCAL_SKILL step
→ one durable NSLStepExecutionBinding
→ UNIQUE (tenant_id, executable_step_id)
→ binding committed before backend call
```

```text
P5 StepResult = schema 1.1 historical
P6 StepResult = schema 1.2 current

non-NSL:
  business_operation_id = null
  operation_fingerprint = null

LOCAL_SKILL READ:
  business_operation_id = stable non-null
  operation_fingerprint = null
```

```text
eligible RuntimeJob selection
+ executor capability filter
+ lease CAS
= one claim transaction
```

```text
one DB-protected dispatcher leader per AE Runtime queue
bounded round
oldest runnable work + tenant_id tie-break
```

```text
timeline = deterministic read projection
no invented state history
unknown optional fields = null
```

## 6. Source Availability Gate

Current NSL v0.1 source baseline:

```text
nurigitdev/2608_nsl
803f22aadc3946a48b05472c80b60fe11d9d9554
```

P6-CA01 in the Codex implementation workspace must independently verify/materialize its actual checkout SHA before closure. A specific filesystem path is not normative.

P6-CA01 refreshed the workspace evidence and confirmed a clean NSL v0.1
checkout at the expected `803f22a...` baseline. The source-backed closure and
Golden READ fixture are recorded in the CA01 closure document.

## 7. P6-CA01 Result

P6-CA01 closed:

- the six transition schemas and validated Golden examples;
- identity/cardinality and StepResult v1.2 rules;
- exhaustive v0.1 request/status mappings;
- the bounded context and artifact/trust projections;
- the `NSL_V01_PROCESS_ISOLATED` production profile;
- worker/atomic-claim inputs and timeline source limits; and
- the source-backed signed Golden READ fixture.

## 8. P6-S0 Result

P6-S0 implemented the dedicated AE Agent Runtime worker foundation:

- exact source-backed capability profile and deterministic profile hash;
- fail-closed configured-executor/backend startup validation;
- independently runnable `--check` entrypoint;
- PostgreSQL-backed readiness and heartbeat lifecycle;
- bounded polling, active-claim accounting, graceful drain and signal adapter;
- lease-safe handler failure that leaves RuntimeJob settlement to its authority;
- restart-safe execution with no process-local work authority; and
- actual `nex_ae_test` RuntimeJob/attempt/heartbeat acceptance with zero residue.

P6-S1 now composes the DB-protected tenant dispatcher and capability-aware
assignment source. Process execution remains fail-closed until P6-S4 provides
the `LOCAL_SKILL` handler.

## 9. P6-S1 Result

P6-S1 implemented:

- one DB-lease-protected dispatcher leader per queue with fencing tokens;
- bounded oldest-runnable tenant discovery and one visit per tenant per round;
- global, per-tenant, round and runnable-depth capacity controls;
- capability-aware RuntimeJob claim with the executor filter and lease CAS in
  one transaction;
- explicit retryable `DELAY` and `REJECT` admission errors;
- malformed-job dead-letter reconciliation with a durable issue ledger;
- a bounded, privacy-safe, AG-only read operations projection; and
- actual `nex_ae_test` PostgreSQL acceptance with migration currency, leader
  failover, stale-leader fencing, lease reclaim and zero residue.

P6-S1A then hardened the completed dispatcher semantics without adding a
migration: dispatch issue IDs no longer occupy `RuntimeJob.reconciliation_id`,
platform-known P5 executors remain queued when the active Agent Runtime worker
pool lacks their capability, and the protected operations projection exposes
that demand as `NO_CAPABLE_WORKER`.

## 10. P6-S2 Result

P6-S2 implemented:

- a structural resolver port compatible with the public NSL v0.1
  `VerifiedPackageSkillResolver`;
- exact Skill/version, semantic hash, package hash, and signing-key binding;
- a separate tenant-scoped current trust/admission source;
- production fail-closed handling for unsigned, untrusted, inactive, rejected,
  mismatched, or future-dated evidence;
- shared canonical hashes for bounded trust, admission, and artifact records;
- immutable tenant-scoped `ae_nsl_artifact` persistence without raw package,
  NSO, signature, or verification-journal content; and
- actual `nex_ae_test` PostgreSQL acceptance with 14/14 checks and zero
  residue.

## 11. P6-S3 Result

P6-S3 implemented:

- one immutable, tenant-scoped `ae_nsl_step_execution` row per executable
  step, with separately allocated NSL execution and BusinessOperation IDs;
- bounded context projection and canonical `SkillExecutionRequest` validation,
  persistence, hashing, restart replay, and private-material rejection;
- exact persisted AgentContext, compiled Skill selector, and verified artifact
  lineage checks before binding;
- StepResult readers/writers that preserve historical schema 1.1 while adding
  schema 1.2 and non-null BusinessOperation ID only for `LOCAL_SKILL`;
- actual `nex_ae_test` PostgreSQL acceptance with 20/20 checks and zero
  residue; and
- an AE Slice Gate with statement 98.67% and branch 96.95% coverage.

S3 deliberately accepted the planned `LOCAL_SKILL_UNAVAILABLE` boundary for
request binding without making it executable. P6-S4 subsequently activated
`executor_kind=LOCAL_SKILL` only after checking every required runtime
dependency.

## 12. P6-S4 Result

P6-S4 implemented:

- additive capability snapshot and executable plan schema 1.2 for exact
  local-Skill bindings while preserving P5 schema 1.1;
- deterministic `LOCAL_SKILL` compilation with exact Skill, semantic,
  contract, trust, package, and backend-profile binding;
- fail-closed executor registration only when artifact gateway, binding
  repository, request builder, selected backend, and result mapper exist;
- worker startup capability/backend declarations derived from the composed
  executor registry;
- migration `2203_ae_local_skill_activation` with no new table; and
- actual `nex_ae_test` acceptance with 19/19 checks and zero residue.

S4 does not invoke the NSL runtime. P6-S5 subsequently completed the
process-isolated NSL READ adapter and execution orchestration.

## 13. P6-S5 Result

P6-S5 implemented:

- explicit `NSLReadBackend` and `V01ReadBackendAdapter` boundaries;
- exact platform-to-v0.1 job mapping without collapsing platform identities;
- spawned-process execution through stable `nsl.api` worker contracts;
- timeout, crash, target-error and malformed-protocol containment;
- ordered progress and audit/snapshot evidence bridging;
- immutable attempt-scoped `ae_nsl_backend_run` persistence through migration
  `2204_ae_nsl_backend_run`; and
- source-backed actual PostgreSQL acceptance with 26/26 checks and zero
  residue.

The adapter was proven against the exact clean NSL v0.1 revision and signed
golden package. P6-S6 subsequently maps its terminal envelope into platform
result and timeline records.

## 14. P6-S6 Result

P6-S6 implemented:

- bounded `NSLResultSummary` mapping from exact binding, artifact and backend
  attempt evidence;
- exhaustive terminal status mapping and false-success rejection for process
  isolation failures;
- compare-and-set binding terminalization with stable summary reference/hash;
- `StepExecutionOutcome` integration into the existing multi-step engine and
  durable LOCAL_SKILL `StepResult v1.2`;
- deterministic complete-retained-evidence timeline reconstruction over ten
  existing AE source families;
- explicit projection-gap metadata instead of fabricated transition history;
- no migration or independent timeline source of record; and
- actual `nex_ae_test` acceptance with 20/20 checks, 21 timeline events and
  zero residue.

The S6 AE Slice Gate passed 3708 tests with statement 98.66% and branch 96.88%
coverage. P6-S7 subsequently completed the IA READ journey through
`AgentResult` while `ResultDelivery` remains pending.

## 15. P6-S7 Result

P6-S7 implemented and proved:

- canonical verified-artifact, durable request, process-isolated READ and
  result-integration composition for the `LOCAL_SKILL` handler;
- actual dispatcher leadership, capability-aware claim and bounded Agent
  Runtime worker consumption;
- dependent deterministic report execution through the existing P5 engine;
- atomic `AgentResult` plus required `ResultDelivery(PENDING)` finalization;
- deterministic timeline reconstruction, restart replay and worker dedup;
- no raw NSL runtime result in the deterministic AgentResult; and
- actual `nex_ae_test` acceptance with 23/23 checks, 29 timeline events and
  zero residue against exact NSL revision `803f22a...`.

The corrected AE Slice Gate includes `test_p5_*` and `test_p6_*` by default.
It passed 3812 tests with statement 98.66% and branch 96.88% coverage; the new
S7 runtime module is 100% statement and branch covered. P6 adds no migration
after `2204_ae_nsl_backend_run`.

## 16. Exit Shape

```text
PROMPT
→ AgentExecution
→ WorkIntent
→ AgentContext
→ AgentPlan
→ VALID
→ ExecutablePlan
→ LOCAL_SKILL ExecutableStep
→ AE RuntimeJob
→ capability-aware AE Worker
→ VerifiedSkillArtifact
→ durable NSLStepExecutionBinding
→ SkillExecutionRequest
→ NSL READ Backend
→ NSLResultSummary
→ StepResult v1.2
→ AgentResult
```

No NSL WRITE, WC, blind replay or false publication success.
