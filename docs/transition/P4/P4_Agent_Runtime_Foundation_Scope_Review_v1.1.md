# P4 Agent Runtime Foundation Scope Review v1.1

**Status:** ARCHITECTURE-CLOSED SCOPE
**Supersedes:** `P4_IA_Runtime_Foundation_Scope_Review_v1.0.md`

## 1. Correction

The prior review correctly detected that generic IA prompts may arrive before Project resolution. Its solution introduced a parallel runtime (`IAChatRun`) and deferred canonical AgentExecution.

DEC-01~DEC-07 supersede that solution.

## 2. Canonical Runtime

```text
authenticated prompt
→ ACTIVE IA from canonical Agent Registry
→ ExecutionTrigger(PROMPT, project_id nullable after P4-CA01)
→ AgentExecution
→ RuntimeJob
→ ExecutableStep
→ existing Chat/RAG application service
→ AgentResult
→ PENDING required WORKSPACE_RESULT ResultDelivery
```

No `IAChatRun` exists.

## 3. IA Boundary

P4 uses canonical:

```text
ae_agent_identity
agent_type = IA
```

P4 MAY add one AE-local `(tenant_id, principal_ref) → agent_id` assignment table.

That table is not an Agent identity SoR.

Login does not mint a new IA per session. Lazy first-prompt provisioning MAY create one canonical IA plus assignment under concurrency-safe constraints.

## 4. Project-neutral PROMPT

Conversation remains project-neutral.

Before Project resolution:

```text
ExecutionTrigger.project_id = null
```

is permitted only after P4-CA01 passes.

No placeholder/default Project is allowed.

## 5. Conversation

KEEP:

```text
Workspace 1:N Conversation
Conversation 1:N append-only Message/Event
```

- no project_id on Conversation;
- existing `chat_document_id` remains compatibility/default Conversation identity;
- `ae_chat_interactions` stays the mutable v1.0 projection;
- new journal is append-only for ordinary application behavior;
- full content stays in owner-private storage.

This is not canonical Agent Memory.

## 6. Weekly Digest

REMOVED from P4.

No digest tables, digest jobs, summarizer, compaction or retrieval injection.

## 7. AgentResult / Publication

P4 implements canonical AgentResult.

P4 creates exactly one required workspace ResultDelivery in `PENDING`.

P4 does not implement publication preflight or ACK.

Therefore canonical AgentExecution does not enter `SUCCEEDED`.

Legacy Chat/RAG response remains backward compatible.

## 8. In Scope

- Chat application-service refactor
- canonical IA identity
- principal-to-IA assignment
- project-neutral canonical PROMPT admission after P4-CA01
- AgentExecution
- RuntimeJob/Attempt
- ExecutableStep
- existing Chat/RAG compatibility execution
- Conversation 1:N
- append-only journal
- AgentResult
- PENDING required workspace ResultDelivery
- observability, PostgreSQL smoke, rollout, regression

## 9. Out of Scope

- IAChatRun or alternate runtime identity
- Weekly Digest / canonical Agent Memory
- CLAIMED_WORKITEM behavior
- CA/PA/EA runtime
- WC
- NSL
- WRITE
- Approval
- EOS
- WA
- Schedule
- publication ACK/preflight/reconciliation

## 10. Acceptance Boundary

P4 proves the canonical runtime foundation through durable AgentResult and pending publication.

P4 closure evidence SHALL say:

> `P4 Canonical Agent Runtime Foundation — AgentResult durable, publication ACK deferred`

and SHALL NOT claim:

> `Full Agent v2.1 Runtime Conformance`
