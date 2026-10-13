# P4-S4 Canonical AgentExecution Admission

## Goal

Admit the approved project-neutral IA PROMPT as a canonical, durable
AgentExecution without introducing a transition-only run identity.

## Decision

- P4-CA01 `ExecutionTrigger v2.1` is the active trigger authority;
- `PROMPT + IA` permits an explicit null `project_id`;
- `CLAIMED_WORKITEM` execution remains outside P4;
- trusted principal assignment resolves the server-managed IA; browser
  `agent_id` is not accepted;
- trigger envelope fields are normalized into `ae_agent_execution` rather than
  creating a second trigger SoR;
- duplicate `(tenant_id, trigger_id)` returns the same execution only when all
  admission semantics match;
- the initial Frozen state/phase is `QUEUED / INTAKE`;
- state changes use version CAS and only Frozen vocabulary;
- `SUCCEEDED` is rejected until required delivery ACK is explicit.

Rollout remains `disabled` by default. `shadow` records typed canonical
admission failures without replacing a valid legacy path; `required` fails
closed. P4-S4 does not invoke Chat/RAG or create a RuntimeJob.

## Verification

Tests cover amended schema validation, null/non-null Project PROMPT admission,
CLAIMED_WORKITEM and PA negatives, trusted IA and Conversation scope, duplicate
idempotency/conflict, Frozen state/phase CAS, delivery ACK guard, all rollout
modes, persistence failures, and migration constraints.

Result:

- AE Slice Gate: `2993 passed, 5 skipped`;
- overall coverage: statement `98.35%`, branch `96.26%`;
- `agent_execution.py`: statement `99.48%`, branch `98.28%`;
- contract validation: 174 schemas, 236 positive examples, 204 negative
  examples, and 7 OpenAPI documents.
