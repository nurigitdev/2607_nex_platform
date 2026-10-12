# P4 Source Audit and Implementation Plan v1.0

**Status:** STEP 9 NARROWED REVIEW BASELINE
**Prepared:** 2026-10-12
**Scope:** project-neutral IA runtime foundation for existing Chat/RAG
**Implementation state:** NOT STARTED
**Scope companion:** `P4_IA_Runtime_Foundation_Scope_Review_v1.0.md`

This plan converts the corrected STEP 9 scope into an implementation-ready
sequence. It does not amend Frozen assets, does not claim full P4 SRS
acceptance, and does not authorize Project, Enterprise OS, PA, WC, or canonical
result-publication work.

## 1. Authority and Guardrails

```text
Frozen semantic authority
> P4 Agent Runtime Foundation SRS
> STEP 8.1 result/publication hardening design
> STEP 9 IA Runtime Foundation scope review
> this source-backed implementation plan
> implementation convenience
```

The STEP 9 scope review narrows implementation where higher documents require
authority that P4 cannot truthfully provide. It never redefines a Frozen
contract. Deferred conformance remains explicit.

Mandatory rules:

1. `docs/frozen/v2.1/` remains byte-identical.
2. Public authenticated Chat/RAG APIs and Web behavior remain compatible.
3. Browser tenant, owner, agent, or Project values are not authority.
4. Workspace 1:N Conversation is introduced without a Project relationship.
5. IA is persistent and personal per tenant/principal. Login creates no IA;
   the first authenticated prompt provisions or resolves it idempotently.
6. P4 uses no `project_id`, Project Agent, Enterprise OS emulator, or WC.
7. P4 uses the name `IAChatRun`; it does not call the transition row a
   conformant ExecutionTrigger, AgentExecution, AgentResult, or ResultDelivery.
8. Complete Conversation content is preserved through an append-only,
   owner-private journal; raw content is not copied into runtime metadata.
9. Async continuation does not replay Chat/RAG generation.
10. A skipped protected smoke is not passing evidence.
11. PERSONAL scope and Conversation Weekly Digest are P4 transition concepts,
    not a default Project or canonical Agent Work Memory.

## 2. Current-State Source Audit

### 2.1 Chat/RAG orchestration

`services/nex-ae-api/nex_ae_api/chat.py` currently owns authorization,
workspace binding, idempotency, runtime policy, prompt binding, interaction
persistence, retrieval, synchronous/asynchronous generation, response lineage,
analytics, cancellation, recovery, and retry orchestration.

The retry path re-enters route behavior, so the first Slice must extract a
callable application service before any runtime wrapper is added. Routes remain
HTTP adapters; the application service remains the single owner of existing
Chat/RAG behavior.

### 2.2 Authentication and owner scope

`route_auth.py` and `auth_guard.py` already provide the correct P4 trust
boundary: tenant and owner derive from validated OA claims, service callers use
validated service identity, and browser payloads cannot override owner scope.
P4 reuses that boundary and adds only server-managed IA resolution.

### 2.3 Workspace and Conversation gap

Migration `1014_ae_workspace_activity_persistence.sql` stores one unique
`chat_document_id` on `ae_workspaces`, and the current binder rejects a second
chat document for the same workspace. The physical relationship is therefore
Workspace 1:1 ChatDocument.

The target relationship is Workspace 1:N Conversation. The existing public
`chat_document_id` remains the compatibility value for `conversation_id`; a CX
`document_id` remains unrelated.

### 2.4 Conversation journal gap

`ae_chat_interactions` stores a user-message hash and preview, not the complete
prompt. Its current repository also updates and deletes rows, so it cannot be
declared append-only without breaking v1.0 behavior. Generated response
content already uses owner-private storage.

P4 retains `ae_chat_interactions` as a mutable compatibility/read projection
and adds immutable ordered message and event records. Correction, regeneration,
and repair append new records with safe supersession lineage instead of
mutating the journal.

### 2.5 Agent Memory boundary gap

Frozen Agent Memory separates append-only Raw Work History from Project- and
week-partitioned Weekly Summary. P4 has neither authoritative Project context
nor Intent Resolution, so it cannot truthfully create canonical Agent Work
Memory. At the same time, preserving all Conversation interactions without a
bounded compaction seam would leave the foundation incomplete.

P4 therefore adds a Conversation Weekly Digest skeleton only. It is scoped by
Conversation and ISO week, rebuilt from immutable raw events, stored as
immutable OPEN/FINAL/ADDENDUM versions, and maintained through the existing AE
maintenance queue boundary. Production LLM composition and retrieval use are
deferred.

### 2.6 Runtime gap

The source contains no personal IA assignment, IAChatRun, or dedicated IA
runtime job/attempt/step persistence. The shared `service_jobs` queue is a
useful algorithmic reference but does not own this lifecycle.

### 2.7 Frozen contract conflict

The Frozen PROMPT ExecutionTrigger requires `project_id`, while the Frozen
Intent design allows an IA prompt to begin before an authoritative Project is
known. P4 has no Enterprise OS, Project resolver, or WC and must not synthesize
a Project.

Consequently P4 implements `IAChatRun` as a transition aggregate and records
the canonical ExecutionTrigger/AgentExecution path as deferred. This is an
explicit limitation, not an alternate interpretation of the Frozen schema.

### 2.8 Async continuation

Synchronous generation may terminalize during create; asynchronous generation
terminalizes through refresh, cancellation, or recovery. P4 maps both paths to
one compatibility step. The authoritative terminal event admits a deduplicated
continuation job and never invokes generation again.

## 3. Target Domain and Source Structure

### 3.1 Domain model

```text
IAIdentity
IAAssignment
IAPersonalScope
Conversation
ConversationMessage
ConversationEvent
ConversationWeeklyDigest
IAChatRun
IARuntimeJob
IARuntimeJobAttempt
IACompatibilityStep
```

`ChatInteraction`, CX job/generation identity, GeneratedResponse, and private
artifacts keep their v1.0 meanings.

### 3.2 Planned source structure

| Path | Responsibility |
|---|---|
| `services/nex-ae-api/nex_ae_api/chat_application.py` | Callable create/refresh/cancel/recovery orchestration. |
| `services/nex-ae-api/nex_ae_api/chat.py` | HTTP parsing, authorization, and response mapping. |
| `services/nex-ae-api/nex_ae_api/conversations.py` | Owner-scoped Workspace 1:N Conversation lifecycle. |
| `services/nex-ae-api/nex_ae_api/chat_message_storage.py` | Ordered metadata and owner-private content. |
| `services/nex-ae-api/nex_ae_api/conversation_journal.py` | Append-only message/event persistence and replay. |
| `services/nex-ae-api/nex_ae_api/conversation_digest.py` | ISO-week digest versions, source watermarks, and maintenance job contracts. |
| `services/nex-ae-api/nex_ae_api/ia_runtime/models.py` | Project-neutral run/job/step contracts and safe projections. |
| `services/nex-ae-api/nex_ae_api/ia_runtime/registry.py` | IA identity and personal IA assignment. |
| `services/nex-ae-api/nex_ae_api/ia_runtime/personal_scope.py` | Opaque PERSONAL scope resolution without Project authority. |
| `services/nex-ae-api/nex_ae_api/ia_runtime/admission.py` | Idempotent IAChatRun admission and rollout. |
| `services/nex-ae-api/nex_ae_api/ia_runtime/jobs.py` | Durable jobs, attempts, leases, retries, and recovery. |
| `services/nex-ae-api/nex_ae_api/ia_runtime/compatibility.py` | Existing Chat/RAG step and async continuation. |
| `services/nex-ae-api/nex_ae_api/ia_runtime/repositories.py` | SQLAlchemy persistence boundaries. |
| `services/nex-ae-api/nex_ae_api/ia_runtime/observability.py` | Content-free trace and diagnostics. |

No module named `project_authority`, `enterprise_os`, `work_coordination`, or
`project_agent` is added in P4.

## 4. Additive Database Plan

All identifiers remain below PostgreSQL's 63-byte limit.

| Migration | Tables | Purpose |
|---|---|---|
| `2001_p4_ia_registry.sql` | `ae_ia_identities`, `ae_ia_assignments`, `ae_ia_personal_scopes` | Persistent personal IA, ACTIVE assignment, and opaque PERSONAL scope. |
| `2002_p4_conversation.sql` | `ae_conversations`, `ae_conversation_messages`, `ae_conversation_events` | Workspace 1:N Conversation and append-only owner-private journal. |
| `2003_p4_conversation_digest.sql` | `ae_conversation_week_summaries`, `ae_conversation_week_heads` | Immutable OPEN/FINAL/ADDENDUM digest versions and current heads. |
| `2004_p4_ia_chat_run.sql` | `ae_ia_chat_runs` | Project-neutral interaction runtime lineage. |
| `2005_p4_ia_runtime_job.sql` | `ae_ia_runtime_jobs`, `ae_ia_job_attempts` | Durable queue, lease, attempt, retry, and recovery. |
| `2006_p4_ia_runtime_step.sql` | `ae_ia_runtime_steps` | One legacy Chat/RAG compatibility step. |

No P4 migration contains `project_id`, Project master data, AgentResult,
ResultDelivery, publication preflight, or WC state.

## 5. Identity and Idempotency

- `conversation_id` uses the current public `chat_document_id` value during
  compatibility migration.
- one `(tenant_id, principal_ref)` resolves to one persistent IA identity, one
  ACTIVE assignment, and one PERSONAL scope; concurrent first prompts use
  unique constraints plus winner/reload behavior.
- `message_id`, `ia_chat_run_id`, runtime job ID, and runtime step ID are new
  identities.
- Conversation messages/events are append-only; a correction receives a new
  identity and may carry `supersedes_message_id`.
- a digest source set is identified by immutable event watermark plus event-set
  hash; retries with the same source reuse the same semantic version.
- one `(tenant_id, interaction_id)` admits at most one IAChatRun.
- START job deduplication uses the IAChatRun identity.
- CONTINUE job deduplication uses the run identity plus authoritative legacy
  terminal source version or hash.
- runtime retries never generate a new Interaction, CX job, generation, or
  GeneratedResponse identity.
- `correlation_id` maps only when the existing trace has the same scope.
- no random retry value, timestamp, Project placeholder, or process identity
  participates in semantic idempotency.

## 6. Rollout and Rollback

```text
NEX_AE_IA_RUNTIME_MODE=disabled|shadow|required
```

| Mode | Behavior |
|---|---|
| `disabled` | Existing Chat/RAG only; no IA runtime dependency. |
| `shadow` | Resolve IA and persist safe run/job lineage while legacy Chat/RAG remains response-authoritative. Runtime failure cannot replace a successful legacy response. |
| `required` | Require ACTIVE IA and durable run/job admission, then execute the same compatibility path. |

Rollback sets the mode to `disabled` and deploys the prior package. Additive
tables remain auditable; no destructive down migration is required.

## 7. Nine-Slice Implementation Plan

Each Slice completes implementation, focused tests, its quality gate, commit,
and synchronization before the next Slice starts.

### P4-S1: Chat Application-Service Refactor

- extract create/refresh/cancel/recovery orchestration from route recursion;
- preserve public routes, status codes, payloads, and side effects;
- make retry call the application service directly.

Evidence: existing AE Chat tests plus
`tests/test_nex_ae_chat_application.py`. Run the Slice Gate.

### P4-S2: Persistent Personal IA, Lazy Assignment, and PERSONAL Scope

- apply migration `2001`;
- implement persistent IAIdentity, one ACTIVE assignment, and one opaque
  PERSONAL scope per tenant/principal;
- lazily provision the row set on the first authenticated prompt, not login;
- handle concurrent first prompts through unique constraints and winner/reload;
- reject inactive, cross-tenant, conflicting, and browser-authoritative IA;
- retain operator/test pre-provisioning as an optional path.

Evidence: first-prompt provisioning, login non-provisioning, assignment
rotation, concurrent winner/reload, owner isolation, SQLite repository, and
actual PostgreSQL smoke tests. Run the Slice Gate.

### P4-S3: Workspace 1:N Conversation and Append-Only Journal

- apply migration `2002`;
- backfill one default Conversation per existing Workspace;
- remove the new-code 1:1 assumption while retaining the legacy default
  pointer for rollback;
- persist immutable ordered messages/events and owner-private content;
- append correction/repair records with supersession lineage;
- retain `ae_chat_interactions` as the v1.0 mutable compatibility projection;
- omit every Project column and relationship.

Evidence: backfill, two-conversation, ordering, replay, mutation-operation
absence, supersession, owner isolation, compensation, SQLite, and PostgreSQL
tests. Run the Slice Gate.

### P4-S4: Conversation Weekly Digest Skeleton

- apply migration `2003`;
- implement ISO-8601 week partitioning in `Asia/Seoul`, including week 53;
- build immutable OPEN_SNAPSHOT, FINAL, and late ADDENDUM versions from the
  complete raw event source;
- persist source watermark/event-set hash and owner-private summary reference;
- define noncanonical maintenance job contracts for refresh, finalize, and
  addendum;
- use deterministic/mock summary composition only.

Evidence: week boundary, week 53, version immutability, full-source recompute,
late-event addendum, source-hash idempotency, owner isolation, queue-contract,
SQLite, and PostgreSQL tests. Run the Slice Gate.

### P4-S5: Project-Neutral IAChatRun Admission

- apply migration `2004`;
- add deterministic admission, lifecycle, optimistic versioning, and terminal
  legacy result references;
- implement disabled/shadow/required modes;
- label diagnostics as IA Runtime Foundation, not AgentExecution conformance.

Evidence: mode, duplicate admission, stale version, missing/inactive IA,
cross-owner, privacy, and naming-contract tests. Run the fifth-Slice
Checkpoint Gate.

### P4-S6: Durable IA Runtime Job and Lease

- apply migration `2005`;
- implement START and CONTINUE jobs;
- implement attempts, lease token, expiry, retry, stale-worker rejection, and
  restart reclaim.

Evidence: queue state matrix, duplicate claim, lease expiry, stale commit,
retry budget, restart, SQLite, and PostgreSQL tests. Run the Slice Gate.

### P4-S7: Legacy Chat/RAG Compatibility Step

- apply migration `2006`;
- execute the extracted Chat application service exactly once;
- map synchronous terminal completion;
- wait and resume asynchronous generation from authoritative terminal state;
- deduplicate refresh/cancel/recovery continuation.

Evidence: sync, async, duplicate continuation, cancellation, failure,
restart, and provider call-count tests. Run the Slice Gate.

### P4-S8: Observability and Protected PostgreSQL Runtime Smoke

- add content-free run/job/step trace projection and metrics;
- prove migrations, lazy IA/PERSONAL resolution, append-only Conversation
  journal, digest lifecycle, run/job claim, restart reclaim, and cleanup
  against the real AE test database;
- prove no Project/EOS/WC dependency or raw content leakage.

Evidence: diagnostics tests and a non-skipped protected PostgreSQL report with
row-count and zero-residue assertions. Run the Slice Gate and risk-based broad
regression because this Slice crosses persistence and restart boundaries.

### P4-S9: Foundation Closure

- run full regression and coverage gates;
- run actual PostgreSQL protected smoke;
- run the existing authenticated Korean Chat/RAG Playwright golden journey;
- verify Frozen checksums and explicit excluded-scope scans;
- publish a closure report that says `P4 IA Runtime Foundation`, not full
  canonical Agent Runtime or Agent Memory conformance.

Run the Full Gate.

## 8. Test Cadence

- Slice Gate for P4-S1 through P4-S4 and P4-S6 through P4-S8;
- fifth-Slice Checkpoint Gate at P4-S5;
- Full Gate at P4-S9;
- immediate Full Gate escalation for unexplained regression, migration/trust
  failure, or idempotency/restart failure.

Repository thresholds remain authoritative:

```text
statement coverage >= 95%
branch coverage    >= 94%
```

## 9. Protected PostgreSQL Smoke Assertions

The protected smoke must prove SQL effects, not connection readiness:

1. apply all AE migrations to the isolated AE test database;
2. issue concurrent first authenticated prompts and prove exactly one IA,
   ACTIVE assignment, and PERSONAL scope;
3. create one Workspace with at least two Conversations;
4. append owner-private messages/events and prove there is no ordinary journal
   mutation path;
5. produce mock-composed OPEN snapshots, FINAL, and late ADDENDUM with stable
   source watermarks and event-set hashes;
6. admit one IAChatRun and one START job;
7. claim with a lease and reject a stale lease commit;
8. restart the repository/process boundary and reclaim eligible work;
9. complete sync or fixture-backed async compatibility lineage exactly once;
10. query all rows through a fresh session and prove duplicate row counts
    remain stable;
11. clean only smoke-owned rows/objects and prove zero residue.

The report records executed, passed, failed, skipped, database identity,
migration head, row-count assertions, restart evidence, and cleanup without
credentials or message content.

## 10. Deferred Design Ledger

The following remain valid future work but have no P4 implementation Slice:

- authoritative Project discovery and clarification;
- Enterprise OS Project resolution;
- Project Agent identity/lifecycle;
- WC delegation and WorkResult;
- canonical PROMPT ExecutionTrigger and AgentExecution;
- complete AgentResult envelope and semantic hash;
- ResultDelivery, publication preflight, ACK, and completion gate;
- canonical Raw Work History and Project-partitioned Agent Weekly Summary;
- production LLM digest composition, digest scheduling, and memory retrieval
  injection;
- Intent, Context, Plan, Compiler, NSL, WRITE, and approval.

STEP 8.1 documents preserve the result/publication decisions until this future
boundary is approved.

## 11. STEP 9 Gate

Source implementation may begin after this narrowed plan is reviewed. The gate
does not claim full P4 SRS closure. It authorizes only the nine-Slice IA
Runtime Foundation described here.
