# P4 Architecture Closure — DEC-01 to DEC-07 v1.0

**Status:** APPROVED P4 ARCHITECTURE CLOSURE
**Date:** 2026-10-12
**Branch:** `transition/p4-agent-runtime-foundation`
**Higher Authority:** `docs/frozen/v2.1/` Integrated Frozen Set

## Final Decisions

### DEC-01 — Canonical AgentExecution Runtime
P4 SHALL implement the canonical AgentExecution Runtime.

```text
PROMPT
→ ExecutionTrigger
→ AgentExecution
→ RuntimeJob
→ ExecutableStep
→ existing Chat/RAG
→ AgentResult
```

`IAChatRun`, `IARuntimeJob`, and `IARuntimeStep` are rejected as parallel transition identities.

### DEC-02 — Project-neutral PROMPT
The project-neutral IA PROMPT conflict SHALL be resolved through a Controlled Amendment before canonical P4 admission.

```text
PROMPT + IA
→ project_id MAY be null before authoritative Project resolution

CLAIMED_WORKITEM
→ project_id remains required non-empty

PA
→ project_id remains required non-empty
```

No fake/default Project, Workspace-as-Project, Conversation-as-Project, or Enterprise OS emulator is permitted.

### DEC-03 — IA Identity
IA identity SHALL use Frozen `ae_agent_identity`.

P4 SHALL NOT create `ae_ia_identities`.

```text
ae_agent_identity
agent_type = IA
project_id = NULL allowed
```

A small principal-to-IA assignment table MAY be added; it is not a second Agent Identity SoR.

### DEC-04 — AgentResult / ResultDelivery
P4 SHALL implement canonical AgentResult.

P4 SHALL also persist the minimum ResultDelivery foundation:

```text
AgentResult = durable / immutable

required WORKSPACE_RESULT ResultDelivery
= PENDING

publication preflight / ACK
= deferred
```

AgentExecution SHALL NOT enter `SUCCEEDED` while the required delivery is not ACKNOWLEDGED.

### DEC-05 — Conversation 1:N + Append-only Journal
KEEP.

```text
Workspace 1:N Conversation
Conversation 1:N immutable Message/Event
```

Conversation remains project-neutral. Existing `ae_chat_interactions` remains the mutable v1.0 compatibility projection. The new journal is not canonical Agent Memory.

### DEC-06 — Weekly Digest
REMOVE from P4.

Weekly digest, compaction, summarizer, schedule, and retrieval injection move to a later Agent Memory phase.

### DEC-07 — Canonical Frozen Runtime Chain
Use canonical Frozen identities from the start.

No intermediate parallel runtime aggregate is allowed.

## Removed Prior Transition Concepts

```text
IAChatRun
IARuntimeJob
IARuntimeStep
ae_ia_identities
IAPersonalScope product concept
ConversationWeeklyDigest
```

## Retained

```text
Frozen ae_agent_identity
principal-to-IA assignment
Workspace 1:N Conversation
append-only Conversation Message/Event journal
AgentExecution
Frozen ae_runtime_job / ae_runtime_job_attempt
ExecutableStep
existing Chat/RAG compatibility adapter
AgentResult
PENDING required WORKSPACE_RESULT ResultDelivery
```

## Final P4 Boundary

```text
IN P4
- canonical IA identity
- Conversation 1:N + append-only journal
- ExecutionTrigger(PROMPT)
- AgentExecution
- RuntimeJob / Attempt
- ExecutableStep
- existing Chat/RAG compatibility step
- AgentResult
- ResultDelivery PENDING foundation
- trace / rollout / regression

NOT IN P4
- CLAIMED_WORKITEM behavior
- CA / PA / EA execution
- WC
- NSL
- WRITE
- Approval
- Enterprise OS
- WA
- Schedule
- Weekly Digest / canonical Agent Memory
- ResultDelivery ACK / full publication
```

> **P4 Architecture Closure DEC-01~DEC-07 — APPROVED**
