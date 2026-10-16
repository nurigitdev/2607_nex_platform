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
→ P6 Full Gate Closure
→ P6-CA02 In-Process Runtime Profile Clarification
→ P6-CA02-S1 Dependency Compatibility / Wheel Admission
→ P6-CA02-S2 Dual-Profile Contract / Persistence Compatibility
→ P6-CA02-S3 In-Process NSL READ Backend Adapter
→ P6-CA02-S4 Profile-Aware Backend Routing
→ P6-CA02-S5 Worker Readiness / Default Activation
→ P6-CA02-S6 Timeout / Crash / Lease Recovery
→ P6-CA02-S7 Dual-Profile Parity / PostgreSQL E2E
→ P6-CA02-S8 Runtime-Profile Acceptance / P7 Entry Closure
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
24. `../../slices/p6_s7_e2e_01_ia_read_closure.md`
25. `../../slices/p6_full_gate_closure_evidence.md`
26. `P6_CA02_In_Process_NSL_Runtime_Profile_Clarification_v1.0.md`
27. `../../slices/p6_ca02_s1_nsl_dependency_wheel_admission.md`
28. `../../slices/p6_ca02_s2_dual_profile_compatibility.md`
29. `../../slices/p6_ca02_s3_in_process_nsl_read_backend.md`
30. `../../slices/p6_ca02_s4_profile_aware_backend_routing.md`
31. `../../slices/p6_ca02_s5_worker_readiness_default_activation.md`
32. `../../slices/p6_ca02_checkpoint_gate_evidence.md`
33. `../../slices/p6_ca02_s6_timeout_crash_lease_recovery.md`
34. `../../slices/p6_ca02_s7_dual_profile_parity_postgres_e2e.md`
35. `../../slices/p6_ca02_s8_runtime_profile_acceptance_p7_entry_closure.md`

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

## 16. P6 Full Gate Closure

The post-P6 repository-wide Full Gate passed at revision `284a6d76`:

- 14592 passed, 34 protected tests skipped, zero failures and zero errors;
- statement coverage 97.27% and branch coverage 96.74%;
- 174 schemas, 236 examples, 204 negative examples and 7 OpenAPI documents
  validated; and
- repeated actual `nex_ae_test` plus source-backed NSL acceptance passed all
  23 checks with zero residue.

The skipped fifth-Slice Checkpoint Gate is explicitly waived. Canonical
evidence and raw-report hashes are recorded in
`docs/slices/p6_full_gate_closure_evidence.md`.

## 17. P6-CA02-S1 Result

P6-CA02-S1 closed the package admission prerequisite for the in-process
profile without activating that profile:

- NSL and Platform now share a proven `cryptography 46.0.7` resolution;
- NSL revision `3b4cb198...` passed all 1,225 NSL tests at 99.25% combined
  statement/branch coverage;
- two independent builds from the exact clean `git archive` produced the same
  admitted wheel digest;
- wheel METADATA, RECORD integrity and required `nsl.api` imports are
  fail-closed admission inputs; and
- `deployment/locks/nsl-v0.1-wheel.json` pins source, wheel and Platform lock
  lineage.

No database migration, PostgreSQL smoke or remote provider was required. The
existing process-isolated runtime remains active until a later Slice composes
and advertises `NSL_V01_IN_PROCESS` readiness.

## 18. P6-CA02-S2 Result

P6-CA02-S2 established dual-profile contract and persistence compatibility:

- new LOCAL_SKILL capability compilation defaults to `NSL_V01_IN_PROCESS`;
- historical `NSL_V01_PROCESS_ISOLATED` bindings remain readable and are not
  rewritten;
- migration `2205_ae_nsl_dual_profile` admits both exact values in durable NSL
  step bindings;
- binding replay, RuntimeJob claim and executor composition preserve the exact
  compiled profile and fail closed instead of falling back; and
- unsupported-profile work remains queued for a capable worker.

Actual `nex_ae_test` smoke passed all 9 checks for separate in-process and
process-isolated round trips with zero residue. The NeX-AE Slice Gate passed
3,824 tests with 98.64% statement and 96.84% branch coverage; contract
validation remained green. In-process adapter implementation and worker
readiness advertisement remain the next Slice boundary.

## 19. P6-CA02-S3 Result

P6-CA02-S3 implemented the actual in-process NSL v0.1 READ adapter without
changing P6 identity, request, result, or persistence contracts:

- the adapter uses only the stable `nsl.api` boundary;
- every execution creates a fresh progress sink and worker session;
- target and protocol failures are contained in existing backend-run evidence;
- timeout semantics are explicitly cooperative, not hard process isolation;
- the admitted wheel `0.1.0` and `cryptography 46.0.7` executed from the
  installed Platform environment; and
- historical process-isolated behavior remains available.

Protected installed-wheel smoke passed all 10 checks. The NeX-AE Slice Gate
passed 3,840 tests with 98.61% statement and 96.82% branch coverage; contract
validation remained green. No database migration, PostgreSQL, or remote model
provider was required. Worker readiness advertisement and default profile
activation remain the next Slice boundary.

## 20. P6-CA02-S4 Result

P6-CA02-S4 connected the exact durable profile to the matching runtime backend:

- one fail-closed router supports both admitted P6 backend profiles;
- supported-but-unconfigured and unknown profiles never fall back;
- compiled, persisted, replayed, and newly returned run profiles must agree;
- one `LOCAL_SKILL` executor and its registry now project the exact configured
  backend profile set; and
- historical single-backend construction remains compatible.

Actual `nex_ae_test` smoke passed all 5 aggregate checks across separate
in-process and process-isolated persisted journeys with zero residue. The
NeX-AE Slice Gate passed 3,864 tests with 98.62% statement and 96.83% branch
coverage; the new smoke scope reached 100% statement and branch coverage and
contract validation remained green. No migration or remote provider was
required. Worker composition, readiness coupling, and controlled default
activation remain the next Slice boundary.

## 21. P6-CA02-S5 Result

P6-CA02-S5 activated the admitted in-process runtime as the initial worker
profile and made package readiness a startup prerequisite:

- environment-loaded workers now default to `NSL_V01_IN_PROCESS`;
- worker process-isolation requirements are inferred from the selected profile
  set;
- wheel version/digest/origin, Platform dependency lock, `cryptography`
  version and the stable `nsl.api` surface are checked fail-closed;
- enabled workers advertise the in-process capability only after readiness
  passes; and
- explicit process-isolated and dual-profile configurations remain valid.

Protected smoke used the actual installed `nex-skill-language 0.1.0` wheel and
passed all 8 readiness/default/compatibility checks. The final NeX-AE Slice
Gate passed 3,880 tests with 98.61% statement and 96.83% branch coverage;
contract validation remained green. No database migration, PostgreSQL, or
remote model provider was required.

## 22. P6-CA02 S1-S5 Checkpoint Gate

The fifth-Slice Checkpoint Gate passed after P6-CA02-S5:

- 13,965 non-closure tests passed with zero failures or errors;
- statement coverage was 98.99% and branch coverage was 97.60%;
- 174 schemas, 236 examples, 204 negative examples and 7 OpenAPI documents
  passed contract validation;
- P6-CA02-S2 and S4 connected directly to `nex_ae_test`, confirmed migration
  `2205_ae_nsl_dual_profile`, exercised both exact profiles and left zero
  residue; and
- P6-CA02-S3 and S5 used the actual installed NSL wheel and passed 10/10 and
  8/8 checks respectively.

The 33 conditional skips belong to unrelated protected environments; none of
the four explicitly selected P6-CA02 smokes was skipped. Remote model
providers were not required. Canonical evidence is recorded in
`docs/slices/p6_ca02_checkpoint_gate_evidence.md`. The repository-wide Full
Gate remains required at P6-CA02 closure or before P7 entry.

## 23. P6-CA02-S6 Result

P6-CA02-S6 hardened timeout, crash, and RuntimeJob lease recovery without a
schema change:

- multi-step begin, waiting, and terminal mutations now fence on the exact
  persisted job/attempt lease inside the mutation transaction;
- stale attempts cannot persist StepResult or WAITING state after reclaim;
- the P5 worker uses its actual post-execution observation time for lease
  authority and settlement;
- in-process timeout remains an NSL cooperative deadline, while process-
  isolated timeout and crash remain distinct retryable evidence; and
- worker disappearance is recovered through `LEASE_EXPIRED ->` a new attempt,
  without synthesizing backend success.

Actual `nex_ae_test` smoke passed all 19 checks with migration
`2205_ae_nsl_dual_profile` current and zero residue. The final NeX-AE Slice
Gate passed 3,890 tests with 98.62% statement and 96.84% branch coverage; the
new protected smoke scope reached 100% statement and branch coverage, and
contract validation remained green. No remote model provider was required.

## 24. P6-CA02-S7 Result

P6-CA02-S7 proved contract parity between the initial in-process profile and
the optional process-isolated compatibility profile through the complete
durable IA READ path:

- each profile completed dispatcher, worker, NSL READ, result integration,
  StepResult v1.2, AgentResult, restart, and cleanup behavior;
- request, runtime result, result summary, and StepResult stable semantics
  matched across profiles;
- execution identities and tenant-scoped opaque refs differed only where
  expected and retained exact lineage inside each journey;
- Runtime imports resolved from the admitted installed wheel rather than the
  source checkout; and
- historical P6-S7 source admission now follows the canonical wheel lock
  instead of an obsolete duplicated SHA.

Actual `nex_ae_test` smoke passed 10/10 checks and all 5 parity dimensions for
both profiles with zero residue. The final NeX-AE Slice Gate passed 3,905 tests
with 98.64% statement and 96.90% branch coverage; both changed smoke scopes
reached 100% statement and branch coverage, and contract validation remained
green. No migration or remote model provider was required.

## 25. P6-CA02-S8 Result

P6-CA02-S8 accepted the runtime-profile baseline for P7:

- the installed-wheel readiness gate passed 8/8 checks;
- timeout, crash, stale-lease rejection, and recovery passed 19/19 checks on
  actual `nex_ae_test` PostgreSQL;
- both runtime profiles passed the complete durable IA READ journey with
  10/10 checks, 5/5 parity dimensions, and zero residue;
- the NSL source gate passed 1,225 tests at 99.47% statement and 98.56%
  branch coverage;
- the repository Full Gate passed 14,710 tests at 97.26% statement and
  96.71% branch coverage; and
- the final protected S8 acceptance passed all 12 checks.

P7 entry is accepted with `NSL_V01_IN_PROCESS` as the initial profile and
`NSL_V01_PROCESS_ISOLATED` as an explicit optional compatibility profile.
Both continue to share one fail-closed AE request, identity, persistence,
result, and timeline contract. No migration or remote model provider was
required for closure.

## 26. Exit Shape

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
