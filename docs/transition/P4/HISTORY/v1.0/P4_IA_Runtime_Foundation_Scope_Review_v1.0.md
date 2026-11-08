# P4 IA Runtime Foundation Scope Review v1.0

> **SUPERSEDED:** Historical P4 v1.0 record. Use the v1.1 baseline in the P4 parent directory.

**Status:** STEP 9 SCOPE CORRECTION
**Prepared:** 2026-10-12
**Scope:** project-neutral IA runtime foundation around the existing Chat/RAG path
**User-interface impact in P4:** NONE

This review narrows P4 after the initial STEP 9 plan pulled Project authority,
Enterprise OS emulation, Project Agent concerns, and canonical result
publication into the first implementation wave. Those concerns are valid in
the target architecture, but they are not prerequisites for the P4 IA runtime
foundation.

This document does not amend the Frozen baseline, the P4 SRS, or the STEP 8.1
hardening record. It records the smaller implementation boundary that can be
built without inventing Project authority or claiming unsupported Frozen
contract conformance.

## 1. Source-Based Correction

The Frozen Intent Resolution design establishes this order for an IA prompt:

```text
user prompt
-> non-authoritative IntentCandidate
-> entity selector such as "A project"
-> deterministic entity/context resolution
-> clarification when the Project is ambiguous
-> later project-scoped plan or delegation when required
```

It explicitly says that an IA prompt may have an unclear Project, that a model
must not manufacture an authoritative Project ID, and that the stable ID is
resolved in a later entity/context stage. The Project Agent concept also places
PA and WC delegation behind the IA front door rather than inside every
conversation.

Therefore the earlier STEP 9 decision to bind every Conversation to one
immutable Project was incorrect. It moved a future interaction-level decision
into the Conversation aggregate and would prevent one conversation from
containing both general Chat/RAG turns and later Project-related requests.

Reviewed evidence:

- Frozen Agent Doc 02, `Intent Resolution`, says IA Project context can be
  unclear, preserves a Project mention as an entity selector, prohibits the
  model from issuing a stable ID, and uses clarification when required;
- Frozen Agent Doc 03, `Context Builder`, assigns stable-reference resolution
  to deterministic entity resolvers after WorkIntent exists;
- Frozen Agent Doc 00, `Project Agent Architecture Concept`, places PA as a
  later Project-scoped actor behind the Unified Workspace and IA front door;
- `execution-trigger-v2.1.schema.json` still requires `project_id`, creating a
  real contract conflict rather than permission to bind Conversation early.

## 2. Correct P4 Cardinality

P4 adopts the following minimum model:

```text
Tenant
  1:N User Principal

(Tenant, Principal)
  1:1 ACTIVE personal IA assignment
  1:1 PERSONAL memory scope
  1:N Workspace

Workspace
  1:N Conversation

Conversation
  1:N ChatInteraction
  1:N ConversationMessage
  1:N ConversationEvent
  1:N ConversationWeeklyDigest version

ChatInteraction
  0:1 IAChatRun while the runtime feature is enabled

IA
  1:N IAChatRun across Workspaces and Conversations
```

There is intentionally no Project, Project Agent, Enterprise OS, WC WorkItem,
or delegation relationship in this P4 model.

## 3. Conversation Boundary

A Conversation is an owner-private discussion container, not a unit of Project
authority.

Rules:

- one Workspace may contain many Conversations;
- a Conversation has no `project_id` column or immutable Project binding;
- a Conversation may contain general Chat, RAG, and Project-related language;
- text mentioning a Project remains untrusted interaction content in P4;
- Project candidates, clarification, and authoritative Project resolution are
  later interaction/runtime concerns;
- a future delegated operation carries the resolved Project scope in its own
  execution or WC contract, not as inherited Conversation authority;
- `document_id` remains a CX source-document identity and is never overloaded
  as a Conversation identity.

The existing public `chat_document_id` is retained as the compatibility value
for `conversation_id` during P4. No user-facing API or Web navigation change is
required.

The present and future paths are deliberately separated:

```text
P4 now:
Conversation message -> personal IA -> existing Chat/RAG -> Conversation

Later:
Conversation message -> IA intent/entity candidate
                     -> resolve Project or ask the user
                     -> project-scoped WC delegation when required
```

## 4. IA Boundary

P4 introduces a server-managed personal IA identity and assignment:

```text
(tenant_id, principal_ref) -> active IA agent_id
```

The same IA may process many Workspaces and Conversations. A Conversation does
not permanently own an IA. Each admitted interaction resolves the current
ACTIVE assignment from authenticated server context, and the resulting run
records the IA that actually handled it. This preserves historical lineage
when an assignment is rotated.

An IA is a persistent identity, not a process created for every login or
prompt. Login creates or refreshes only the OA-authenticated session. P4 uses
idempotent lazy provisioning on the first authenticated prompt as its normal
path: the server creates or loads the IA identity, ACTIVE assignment, and
PERSONAL scope under unique constraints. Concurrent first prompts may race,
but exactly one row set wins and the losing request reloads it. Operator
pre-provisioning remains available but is not required for an ordinary user.

Every accepted prompt creates a new IAChatRun and runtime job for the existing
persistent IA. It does not create a new IA.

The P4 physical model is IA-only and does not pre-create a generic Agent
Registry shape for PA/CA/EA. Browser-provided `agent_id`, tenant, owner, or
Project hints are never authoritative. P4 adds no public Agent Registry
administration UI.

## 5. Project-Neutral Runtime Intake

Frozen `execution-trigger-v2.1.schema.json` requires `project_id` for a PROMPT,
while generic Chat/RAG and the Frozen Intent Resolution flow do not guarantee a
resolved Project before prompt interpretation. P4 must not hide this conflict
by using any of the following:

- `workspace_id` as `project_id`;
- `conversation_id` as `project_id`;
- a hidden COMMON Project;
- a generated placeholder Project;
- `MOCK_ENTERPRISE_OS`.

P4 therefore introduces a bounded transition aggregate named `IAChatRun`.
`IAChatRun` is project-neutral and is explicitly **not** represented as a
Frozen-conformant `ExecutionTrigger` or `AgentExecution`.

Minimum run fields are:

```text
tenant_id
ia_chat_run_id
agent_id
workspace_id
conversation_id
interaction_id
correlation_id
state
current_step
legacy_result_ref
version
created_at
updated_at
completed_at
```

No raw prompt or generated response body is duplicated into runtime metadata.
The existing Chat/RAG records and owner-private storage remain authoritative
for interaction and response content.

This transition aggregate provides durable admission, job ownership, retry,
restart, and traceability. A later approved phase may create a canonical
AgentExecution after intent and Project resolution, or may amend the Frozen
PROMPT contract for direct project-neutral IA work. P4 does not choose that
future architecture implicitly.

## 6. P4 Runtime Path

The complete P4 path is intentionally small:

```text
authenticated Chat request
-> owner-visible Workspace and Conversation
-> lazy, idempotent personal IA/PERSONAL scope resolution
-> idempotent IAChatRun
-> durable IA runtime job and attempt
-> one legacy Chat/RAG compatibility step
-> existing synchronous or asynchronous CX path
-> terminal legacy interaction/result reference
-> IAChatRun completion
```

Asynchronous generation is resumed from the authoritative legacy terminal
event. A duplicate refresh, recovery, or continuation must not call generation
again.

## 7. Append-Only Conversation Journal

P4 adds an immutable Conversation journal because the current interaction
table stores only a prompt hash and bounded preview, and its rows may be
updated or deleted by existing v1.0 workflows. That current table remains a
mutable compatibility/read projection. P4 does not break its behavior by
pretending that it is the new source journal.

`ae_conversation_messages` stores ordered user, assistant, and system message
metadata:

```text
tenant_id
message_id
conversation_id
interaction_id
sequence_no
role
status
content_storage_ref
content_sha256
content_size_bytes
content_type
created_at
supersedes_message_id
```

`ae_conversation_events` stores the append-only event sequence used for
replay, digest watermarking, and audit. Application repositories provide no
message/event update or delete operation. Correction, regeneration, and repair
append a new message/event and may reference the superseded message. Legal or
security erasure remains an exceptional controlled lifecycle outside ordinary
Chat mutation; P4 does not attempt to finish that later privacy workflow.

Full user and assistant content uses the existing owner-private storage
boundary. PostgreSQL contains opaque references, hashes, sizes, sequencing,
and safe lineage only. Existing workspace rows are backfilled into one default
Conversation without changing public IDs or Web behavior.

## 8. PERSONAL Scope and Weekly Digest Skeleton

P4 does not create a default Project for personal or unresolved work. Doing so
would make AE a Project authority, falsely classify general conversation as
Project work, and create migration debt for future Project resolution and PA/
WC delegation.

Instead, each personal IA receives a stable opaque `personal_scope_id` under
the authenticated `(tenant_id, principal_ref)` boundary. `PERSONAL` is not a
`project_id`, cannot create a Project Agent, and cannot authorize WC
delegation. A future interaction that resolves a real Project may create
Project-scoped execution/history under a later approved contract.

P4 also adds a bounded `ConversationWeeklyDigest` skeleton so long append-only
conversations have a restart-safe compaction seam without claiming canonical
Agent Work Memory:

- partition by `(tenant_id, conversation_id, iso_week_year, iso_week_no)`;
- derive the week from event `occurred_at` using ISO-8601 Monday boundaries in
  `Asia/Seoul`, including valid week 53 and keys such as `2026-W01`;
- include all Conversation interactions in the source set, independent of
  whether a future Intent Resolver would classify them as Project work;
- build every version from the complete raw event source, never from a prior
  summary;
- preserve immutable `OPEN_SNAPSHOT` versions, one immutable `FINAL`, and
  append-only `ADDENDUM` versions for late events;
- persist source watermark/event-set hash and summary provenance;
- store summary content in owner-private storage and only opaque reference,
  hash, size, and metadata in PostgreSQL;
- use clearly noncanonical maintenance jobs named
  `CONVERSATION_WEEKLY_DIGEST_REFRESH`,
  `CONVERSATION_WEEKLY_DIGEST_FINALIZE`, and
  `CONVERSATION_WEEKLY_DIGEST_ADDENDUM`.

The P4 implementation stops at schemas, repository behavior, job contracts,
and deterministic/mock summarizer tests. It does not add a production LLM
summarizer, schedule daemon, retrieval injection, or canonical Agent Memory.
Digest maintenance uses the existing AE maintenance/service-job boundary, not
IAChatRun, AgentExecution, or IA runtime execution jobs.

## 9. P4 In Scope

- reusable application-service boundary around existing Chat/RAG;
- persistent server-managed IA identity, lazy first-prompt assignment, and
  PERSONAL scope;
- Workspace 1:N Conversation persistence;
- append-only ordered Conversation message/event persistence with the existing
  interaction table retained as a compatibility projection;
- Conversation Weekly Digest schema/repository/job-contract skeleton;
- project-neutral `IAChatRun` admission and lifecycle;
- durable runtime job, attempt, lease, retry, and restart recovery;
- one compatibility step for the existing Chat/RAG path;
- asynchronous continuation without generation replay;
- safe runtime diagnostics and feature rollout;
- actual PostgreSQL smoke and unchanged Chat/RAG browser regression.

## 10. Explicitly Out of Scope

- `project_id` resolution or storage;
- Conversation-to-Project binding;
- Project Agent or any PA registry/lifecycle;
- Enterprise OS adapter or `MOCK_ENTERPRISE_OS`;
- WC, WorkItem, claim, delegation, or WorkResult;
- Intent Resolver, Context Builder, AgentPlan, or Compiler;
- canonical Frozen PROMPT `ExecutionTrigger` admission;
- canonical `AgentExecution` success semantics;
- canonical `AgentResult` and `ResultDelivery` implementation;
- STEP 8.1 publication preflight and ACK processing;
- canonical Project-partitioned Agent Work Memory;
- production LLM digest composition, digest scheduling, or digest retrieval
  injection;
- ordinary update/delete APIs for Conversation journal entries;
- new Conversation-list Web UI;
- CA/PA/EA execution, NSL, WRITE, approval, schedule, or WA.

The STEP 8.1 hardening document remains an approved design record for the
future canonical result/publication phase. Its implementation is deferred, not
discarded.

## 11. Rollout and Naming Guardrail

The feature control is:

```text
NEX_AE_IA_RUNTIME_MODE=disabled|shadow|required
```

- `disabled`: execute the existing Chat/RAG path only;
- `shadow`: persist/trace a project-neutral IAChatRun while the existing path
  remains response-authoritative;
- `required`: require IA assignment and runtime durability, then execute the
  same compatibility path.

The modes refer only to the P4 IA runtime foundation. They must not be named or
reported as Frozen AgentExecution conformance.

## 12. Acceptance Boundary

P4 Foundation acceptance proves all of the following together:

- existing authenticated Chat/RAG behavior and UI remain unchanged;
- one Workspace supports multiple project-neutral Conversations;
- ordered complete turns can be restored from an append-only journal under
  owner isolation while the v1.0 interaction projection remains compatible;
- login creates no IA, while concurrent first authenticated prompts resolve
  exactly one persistent IA, assignment, and PERSONAL scope;
- Conversation Weekly Digest OPEN/FINAL/ADDENDUM versions are immutable,
  source-watermarked, and reproducible from raw events with mock composition;
- one interaction creates at most one IAChatRun;
- durable jobs survive restart and reject stale leases;
- synchronous and asynchronous compatibility work executes once;
- no Project, Enterprise OS, PA, or WC dependency is introduced;
- no default Project or canonical Agent Memory conformance is claimed;
- actual PostgreSQL smoke and regression/coverage gates pass.

This is a deliberately narrower acceptance boundary than full P4 SRS or
Frozen Agent Runtime conformance. That distinction must remain visible in all
reports and commits.
