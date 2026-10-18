# P7-CA01 - Source-Backed WC and Background Agent Contract Closure v1.0

**Status:** CLOSED
**Observed date:** 2026-10-18
**Scope:** P7 Work Coordination and CA/PA/EA background execution foundation
**Reviewed Platform HEAD:** `e2436c9096c048f7cdda8fb3d634155c74546d54`

## 1. Closure Statement

P7-CA01 inspected the Frozen WC/AE contracts, current AE/OA source, and the
shared `services/_shared/nex_runtime` implementation. It closes the contracts
required before P7-S1 without implementing a WC service, migration, claim,
handoff, wait, result publisher, or background Agent execution path.

The implementation authority remains:

```text
Frozen v2.1 contracts
> P6/P6.5 As-Built baselines
> this source-backed closure
> P7 pre-implementation documents
> implementation convenience
```

## 2. Source Baseline and Frozen Integrity

Reviewed current source:

```text
services/_shared/nex_runtime
services/nex-ae-api/nex_ae_api
services/nex-oa/nex_oa
database/nex-ae-api/migrations
database/nex-oa/migrations
```

Frozen WC input digests:

| Input | SHA-256 |
|---|---|
| `002_wc_work_result_v2_1.sql` | `9eaaae64d31065cfc73f3e666a4ee98ef2baa469b492ca732f135faaa1df20eb` |
| `claim-execution-handoff-v2.1.schema.json` | `3f7614fdd5fb2f0ba506281581b7a5158c5a6d92cac50cd61ac9ba6ed6d2f138` |
| `routing-decision-v2.1.schema.json` | `ace386dff6039213885ebd163eda6f65655f8e81a650639244de91a0ced9870e` |
| `wc_protocols_v2_1.py` | `6701e1a2653d9a21ea40aa6e94fee09176dce6e7f693f02c9d7a5d00fb65aed4` |
| `work-item-v2.1.schema.json` | `ee027300754a6aa34706d612fd73a5d4d7edd51b625987bf3be7abd5f4473ff9` |
| `work-result-submitted-event-v2.1.schema.json` | `0015acf1fe492424a7dad1bb99a759bb3bd78e577435fbfc9dee55f55df56c1b` |
| `work-result-v2.1.schema.json` | `4364f1840327146ca34c69589fd66e6d17789ce20ef0d50f78859a9ce0d49ff9` |

The five Frozen JSON schemas under `contracts/` are byte-for-byte extracts.
No Frozen file was edited.

## 3. Current Source Findings

| Boundary | Current source fact | P7 disposition |
|---|---|---|
| WC | service and migration chain absent | add bounded sixth backend in S1 |
| AE identity | DB vocabulary includes IA/CA/PA/EA; repository is IA-only | generalize existing registry in S2 |
| AE execution | Python trigger knows CLAIMED_WORKITEM; DB/repository admit IA/PROMPT only | additive migration and separate admission in S4 |
| DELEGATE_WORK | logical vocabulary exists; validation/compiler reject it | activate only after WC and wait contracts in S5 |
| RuntimeJob | dedicated durable queue supports START/CONTINUE only | add RESUME to the same domain queue in S6 |
| ResultDelivery | WC_WORK_RESULT vocabulary exists; IA finalization is workspace-only | target-specific WC publisher in S6 |
| OA | tenant membership and effective scopes exist; Project authority SoR does not | use current membership/scopes; do not invent Enterprise OS |
| shared runtime | common job, retry/replay, worker, heartbeat, log, event, DB/pool code exists | reuse for WC technical work |

## 4. P7-CA01-DEC-01 - NeX-WC Topology

The service topology is fixed as:

```text
service_id       = nex-wc
package          = services/nex-wc/nex_wc
database         = database/nex-wc
OpenAPI          = contracts/openapi/nex-wc
database env     = NEX_WC_DATABASE_URL
test DB env      = NEX_WC_TEST_DATABASE_URL
persistence mode = NEX_WC_PERSISTENCE_MODE
default port     = 8106
```

`nex_wc_dev` and `nex_wc_test` were reachable as `nex_wc_user` during CA01.
No credential is recorded in source or evidence.

S1 SHALL add `nex-wc` to the canonical `ServiceSpec`, known service ID, signed
token audience, process/deployment manifest, PostgreSQL target, and trust grant
inventories. It SHALL use `build_service_app`,
`attach_service_persistence_runtime`, and existing database pool/readiness
helpers.

## 5. P7-CA01-DEC-02 - Domain SoR Is Not a Job Queue

The following are WC domain records and SHALL NOT be represented as
`common_job.v1`:

```text
WorkItem
RoutingDecision
Assignment
Claim / ClaimGeneration / lease
WorkResult
WC event outbox record
```

The following identities remain distinct:

```text
WorkItemId != ClaimId != AssignmentId != OutboxId != EventId
             != CommonJobId != AgentExecutionId != RuntimeJobId
```

Claim lease is business execution authority. A common job lock is technical
worker ownership. They are not interchangeable.

## 6. P7-CA01-DEC-03 - Shared Runtime Reuse Boundary

WC SHALL reuse these existing common components:

```text
nex_runtime.jobs
  JobQueue / InMemoryJobQueue / SqlAlchemyJobQueue
  build_common_job / validate_common_job
  retry / dead-letter / replay / idempotent enqueue

nex_runtime.worker_runner
  WorkerRunnerConfig / run_worker_once / run_worker_batch

nex_runtime.worker_heartbeats
nex_runtime.job_control
nex_runtime.service_logs
nex_runtime.operational_events
nex_runtime.database / persistence
```

WC SHALL NOT implement a second generic queue, retry calculator, dead-letter
store, replay lineage format, worker heartbeat store, service log store, or job
control API.

The first WC common job is fixed as:

```text
job_type       = WC_EVENT_DELIVERY
subject_ref    = {type: WC_OUTBOX, id: <outbox_id>}
idempotency_key= <event_id>
payload        = {outbox_id, event_id}
max_attempts   = bounded technical policy
```

The job payload contains references only, not the WorkItem goal, result
payload, raw prompt, credential, or event body.

AE `SqlAlchemyRuntimeJobQueue` remains a separate Agent Runtime domain queue.
`RESUME_EXECUTION` is added there, not to the common WC queue.

## 7. P7-CA01-DEC-04 - Migration Profile

The WC chain begins with the established service-local common tables, using
the existing short names:

```text
0023_schema_migrations_baseline
0083_service_job_queue_foundation
0085_service_operational_events_foundation
0112_service_worker_heartbeat_foundation
0135_service_job_replay_lineage
0137_service_log_entries_foundation
1000_wc_work_item
1001_wc_assignment_claim
1002_wc_work_result_outbox
```

The common migration bodies are adapted from the existing service-local
templates, not re-designed. A dedicated `wc_event_delivery_attempt` table is
not created in the initial profile because `service_jobs`, replay lineage,
service logs, and the outbox delivery state already own technical attempt
evidence. A future domain delivery receipt requires a separate decision.

## 8. P7-CA01-DEC-05 - WorkItem Storage and Idempotency

`wc_work_item` is the Work SoR. Initial creation accepts only
`source_type=AGENT_PLAN_STEP` and a validated `DelegationSpec`.

Creation identity is the shared canonical semantic hash of:

```text
tenant_id
parent_agent_execution_id
parent_executable_plan_id
parent_executable_step_id
delegation_revision
```

Rules:

```text
same key + same DelegationSpec semantic hash -> return existing WorkItem
same key + different semantic hash           -> deterministic conflict
new delegation revision                      -> new semantic child WorkItem
```

P7 uses `nex_runtime.semantic_hashes`; no local digest helper is authorized.

Frozen `ACKNOWLEDGED` remains schema-visible but runtime-disabled. The active
P7 state set is:

```text
CREATED -> ROUTED -> ASSIGNED -> IN_PROGRESS
IN_PROGRESS -> BLOCKED | WAITING_INPUT | RESULT_SUBMITTED
RESULT_SUBMITTED -> REVISION_REQUESTED | CLOSED
non-terminal allowed state -> CANCELLED according to policy
```

## 9. P7-CA01-DEC-06 - Agent Registry API and PA Uniqueness

AE extends the existing `ae_agent_identity`; it does not create another
identity table.

Authenticated internal API shape:

```text
POST  /internal/v1/tenants/{tenant_id}/agents
GET   /internal/v1/tenants/{tenant_id}/agents/{agent_id}
GET   /internal/v1/tenants/{tenant_id}/agents
PATCH /internal/v1/tenants/{tenant_id}/agents/{agent_id}/status
GET   /internal/v1/tenants/{tenant_id}/projects/{project_id}/active-pa
```

The bounded list query accepts `agent_type`, `status`, and `project_id`. It
returns AgentIdentity fields including `profile_ref`; it never returns a DB
session, credential, prompt, or mutable authority grant.

The existing Frozen partial unique index is activated:

```text
UNIQUE (tenant_id, project_id)
WHERE agent_type='PA' AND status='ACTIVE'
```

Initial P7 background candidates are project-bound. PA requires an exact
identity project match. A CA/EA identity with null or different project is not
eligible in the initial profile.

## 10. P7-CA01-DEC-07 - Deterministic Capability Eligibility

`AgentIdentity.profile_ref` is not itself renamed into a capability. AE returns
the exact profile reference. WC's versioned routing policy maps:

```text
required_capability -> admitted profile_ref set
```

and stores the policy version and reason codes in `RoutingDecision`.

The initial Golden mapping is:

```text
FINANCE.PROJECT_BUDGET_CHECK
-> agent-profile://pa/project-budget-read/v1
```

An absent mapping, inactive identity, wrong type, wrong tenant, wrong project,
or non-admitted profile produces `UNROUTABLE`; it never falls back to an LLM
choice.

## 11. P7-CA01-DEC-08 - OA Authorization Boundary

Current OA source provides active tenant membership, effective roles/scopes,
and a revision hash. It does not provide an Enterprise OS Project authority
registry. P7 therefore does not invent one.

Exact current checks:

```text
service call        -> audience exact + service:call
WorkItem create     -> requester active + work:delegate
claim commit        -> requester active + work:claim
WorkResult submit   -> requester active + work:result:submit
```

WC calls the existing OA effective-authorization API immediately before each
authority boundary and records a metadata-safe decision reference containing
the authorization revision hash and checked time. It does not cache a prior
routing decision as authorization.

`project_scope_ref` is a trusted bounded selector in P7, not proof that OA
owns a Project. Project exactness is enforced by WorkItem, routing policy, and
AE AgentIdentity. Enterprise OS Project authority remains P8/later scope.

## 12. P7-CA01-DEC-09 - Atomic Claim, Assignment, and Lease

A claim attempt first obtains fresh OA authorization, then one WC transaction:

1. locks the tenant-scoped WorkItem and latest route;
2. checks expected WorkItem version and active state;
3. reloads the exact candidate projection from authenticated AE data;
4. checks type, project, profile/capability, and current Agent status;
5. inserts a Claim with monotonically increasing generation;
6. inserts exactly one active Assignment;
7. updates WorkItem to `ASSIGNED`; and
8. inserts `CLAIM_EXECUTION_HANDOFF` into `wc_event_outbox`.

All eight changes commit or none commit. The raw lease token is returned once;
only its hash-safe verifier is stored. Reclaim is allowed only after expiry or
explicit release and allocates a higher generation. A stale generation cannot
create or mutate an AgentExecution.

## 13. P7-CA01-DEC-10 - Handoff Outbox and Common Delivery Job

The outbox row is committed with Claim/Assignment. It remains the event SoR.
The common JobQueue is only the delivery mechanism:

```text
committed outbox row
-> idempotent bridge enqueue WC_EVENT_DELIVERY(event_id)
-> shared WorkerRunner
-> authenticated AE event API
-> AE inbox insert-or-verify
-> outbox delivered
-> common job SUCCEEDED
```

The bridge marks an outbox row enqueued only after `JobQueue.enqueue` returns.
If it crashes after enqueue, the unique `(job_type, idempotency_key)` returns
the same job on retry. If delivery succeeds remotely but the worker crashes,
AE event dedup makes retry safe.

Technical retry never creates a new WorkItem, Claim, Assignment, handoff,
WorkResult, event ID, or child AgentExecution.

## 14. P7-CA01-DEC-11 - CLAIMED_WORKITEM Admission

AE adds historical-row-safe columns and constraints for:

```text
work_item_ref
claim_ref
claim_generation
assignment_ref
requester_ref
```

`admit_claimed_work()` is separate from `admit_prompt()`. It requires:

```text
source_type = CLAIMED_WORKITEM
agent_type  = CA | PA | EA
active exact AgentIdentity
exact tenant / project / type
complete claim and assignment lineage
```

The dedup identity is `(tenant_id, handoff_id)`. Same identity with different
lineage fails closed. Existing IA/PROMPT rows and behavior remain unchanged.

## 15. P7-CA01-DEC-12 - DELEGATE_WORK Contract

The transition `DelegationSpec` carries bounded semantic requirements only:

```text
goal / work_class
required_agent_type / required_capability
project_ref / project_scope_ref
result_contract_ref / completion_policy
parent execution / plan / step / revision lineage
correlation / causation
```

It cannot carry an actual assignee, ClaimId, AssignmentId, lease, OA decision,
AgentExecutionId, provider route, or credential.

Only a VALID AgentPlan compiles to:

```text
step_type    = DELEGATE_WORK
executor_kind= WC_DELEGATE_WORK
```

The compiler remains provider-free.

## 16. P7-CA01-DEC-13 - Wait, Inbox, and Resume

AE owns `WaitRegistration`; WC does not. The state sequence is:

```text
PENDING -> SATISFIED -> RESUME_QUEUED -> CONSUMED
PENDING -> CANCELLED
```

Identity and uniqueness:

```text
one wait per (tenant_id, agent_execution_id, executable_step_id, wait_type)
one inbox row per (tenant_id, event_id)
one RESUME job per (tenant_id, wait_id, matched_event_id)
```

The same reconciliation transaction locks the wait and matching inbox row,
validates the result contract, marks the wait satisfied, and enqueues exactly
one AE `RESUME_EXECUTION` RuntimeJob. Insert-or-verify plus periodic
reconciliation makes both event-before-wait and wait-before-event converge.

`RESUME_EXECUTION` retains the same parent AgentExecution and waiting
ExecutableStep. It never creates a new execution.

## 17. P7-CA01-DEC-14 - WorkResult and ResultDelivery ACK

A background AgentResult creates required target:

```text
ResultDelivery.target_type = WC_WORK_RESULT
```

AE submits through authenticated HTTP. WC locks the current WorkItem and
validates current Claim/Assignment/generation, result schema, submitter,
requester OA authorization, expected WorkItem version, and idempotency.

One transaction inserts/verifies WorkResult, moves WorkItem to
`RESULT_SUBMITTED`, and inserts `WORK_RESULT_SUBMITTED` in the outbox.

Only WC acceptance of the exact result identity/hash ACKs ResultDelivery.
Transport timeout leaves delivery pending and retries the same semantic result.
The child AgentExecution cannot succeed before required delivery ACK.

`resume_match_ref` must equal `work_item_id`; JSON Schema validation is followed
by this semantic check before inbox matching.

## 18. P7-CA01-DEC-15 - Background Planning Source

P7 generalizes source projection, not the planner:

```text
PlanningSourceAdapter
  IA_PROMPT          -> existing P6.5 path
  CLAIMED_WORKITEM   -> bounded WorkItem projection
```

The claimed-work projection may include goal, work class, required capability,
project ref, admitted artifact/evidence refs, completion policy, and result
contract. It excludes raw parent prompts, secrets, provider configuration,
foreign DB snapshots, and actual claim authority.

Both sources feed the existing P5/P6.5 candidate admission, PlanValidation,
compiler, P6 Runtime, and NSL READ path. No second planner or worker framework
is authorized.

## 19. P7-CA01-DEC-16 - Frozen-Inactive Vocabulary

The following stay schema-visible and runtime-disabled in P7:

```text
WorkItem ACKNOWLEDGED state
HUMAN candidate/assignee
EXTERNAL_AGENT candidate/assignee
HUMAN / EXTERNAL_A2A / SYSTEM / FOLLOW_UP / SCHEDULE sources
Approval / recurring work / multi-child parallel fan-out
```

Encountering one in a create/route/claim runtime request returns a deterministic
unsupported-profile error; it does not silently coerce to the active profile.

## 20. P7-CA01-DEC-17 - Golden B Fixture

The protected P7-S9 journey is fixed as:

```text
tenant       = tenant-a fixture
principal    = employee-100 fixture
project      = project-alpha fixture
required PA  = agent-pa-project-alpha
capability   = FINANCE.PROJECT_BUDGET_CHECK
profile      = agent-profile://pa/project-budget-read/v1
result       = contract://nex/wc/project-budget-analysis/v1
prompt       = 프로젝트 예산 자료를 확인해서 총 예산, 집행액, 잔액을 요약해줘.
```

It uses actual `nex_oa_test`, `nex_ae_test`, and `nex_wc_test`, live MO
generation, and the admitted P6 NSL READ backend. It proves duplicate delivery,
restart/reconciliation, stale claim rejection, ResultDelivery ACK, parent
resume, and zero owned residue.

No live provider is required for CA01 because this Slice adds contracts only.

## 21. Negative Contract Matrix

| ID | Must fail closed |
|---|---|
| P7-CA01-N01 | PA WorkItem missing project reference |
| P7-CA01-N02 | routing candidate Agent type differs from required type |
| P7-CA01-N03 | handoff missing Claim/Assignment/generation lineage |
| P7-CA01-N04 | Agent WorkResult/event missing execution/claim/assignment lineage |
| P7-CA01-N05 | event `resume_match_ref` differs from WorkItem |
| P7-CA01-N06 | DelegationSpec selects actual assignee/claim/authority |
| P7-CA01-N07 | RESUME_QUEUED wait lacks matched event or RuntimeJob identity |
| P7-CA01-N08 | Frozen extract or source digest drifts |
| P7-CA01-N09 | WC introduces a second generic queue/retry/replay implementation |
| P7-CA01-N10 | common job payload contains domain content or credential |

## 22. Slice Authorization

| Slice | Authorized work |
|---|---|
| P7-S1 | service shell, common persistence foundation, WorkItem/route/outbox foundation |
| P7-S2 | CA/PA/EA registry APIs, status, PA uniqueness, profile projection |
| P7-S3 | deterministic route, fresh OA scope check, atomic claim/assignment/lease |
| P7-S4 | outbox delivery job/worker, AE inbox, CLAIMED_WORKITEM admission |
| P7-S5 | DelegationSpec validation, deterministic compile, WC executor, WaitRegistration |
| P7-S6 | WorkResult publisher, ACK, event reconcile, RESUME_EXECUTION |
| P7-S7 | claimed-work planning adapter and existing P6/P6.5 runtime integration |
| P7-S8 | restart, race, replay, stale generation, privacy, operations hardening |
| P7-S9 | actual PostgreSQL + live provider Golden B E2E, Full Gate, P8 handoff |

S1 must review/refactor the owning source before adding the service, but the
shared common runtime itself needs no broad rewrite for P7 entry.

## 23. Verification Evidence

Executed on 2026-10-18:

```text
P7-CA01 focused contract/source tests
  31 passed

shared JobQueue/worker/persistence targeted regression
  137 passed
  statement coverage = 96.15% (required >= 95%)
  branch coverage    = 95.45% (required >= 94%)

P5/P6/P6.5/P7 contract regression + central contract test
  118 passed

repository contract validation
  schemas=174 examples=236 negative_examples=204 openapi=7
  status=PASS

NeX-WC PostgreSQL connectivity
  nex_wc_dev  = PASS
  nex_wc_test = PASS
```

The broader existing `nex-runtime` service-profile Slice Gate executed
successfully at the test level (`1588 passed`, one opt-in PostgreSQL smoke
skipped), but its service-wide coverage scope reported statement `89.52%` and
branch `86.40%`, below `95%/94%`. That denominator includes unchanged
production release/object-storage modules not selected by the runtime service
test profile. CA01 changes no runtime source, and the exact shared JobQueue
dependency scope passes both thresholds as recorded above. The broader profile
coverage mismatch remains visible and is not represented as a passing gate.

No migration or provider call is introduced by CA01. PostgreSQL migration and
live provider evidence therefore remain assigned to their implementation and
P7-S9 closure Slices.

## 24. Exit Decision

All P0/P1 pre-implementation contract ambiguity identified by the P7 baseline
is closed at the source-backed level. P7-S1 is authorized.

```text
LLM proposes bounded semantics.
WC owns work and claims.
OA authorizes current actors.
AE owns agents, waits, and execution.
Shared JobQueue carries technical work only.
```

> **P7-CA01 is closed. P7-S1 is authorized.**
