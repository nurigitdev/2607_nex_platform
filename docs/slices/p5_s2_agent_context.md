# P5-S2 AgentContext

## Scope

- Implement the P5 v1.1 AgentContext builder and immutable generation-based
  persistence boundary.
- Consume bounded context references only through a `TrustedContextResolver`
  port.
- Adapt the existing compatibility RuntimePolicy bare digest to the P5
  semantic `sha256:<digest>` representation without re-hashing it.
- Verify exact AgentExecution and WorkIntent lineage before persistence.

## Decisions

- AgentContext remains project-neutral and may carry `project_ref = null`.
- Context generations are immutable and contiguous per AgentExecution.
- The durable record contains identity, interaction, policy and resource
  references, bounded conflict/degradation metadata, manifest hashes, and token
  budget only. Raw prompts, document bodies, credentials, provider endpoints,
  hidden reasoning, and cross-service database snapshots are rejected.
- WorkIntent ID, revision, hash, and execution scope must match the persisted
  WorkIntent exactly. Principal, IA, workspace, conversation, and interaction
  must match the persisted AgentExecution.
- Current Chat/RAG behavior is unchanged. Production admission wiring remains
  deferred to the later P5 integration path.

## Persistence

- `2102_ae_agent_context.sql` adds `ae_agent_context` with immutable context
  identity, execution/generation uniqueness, WorkIntent and AgentExecution
  foreign keys, semantic hashes, and JSON identity constraints.
- Table, constraint, and index names stay within PostgreSQL limits.

## Verification

- Focused P5-S2 regression: `62 passed` including S1 smoke-contract regression.
- `nex_ae_api.agent_context` reached `100%` statement and branch coverage.
- Actual PostgreSQL smoke used `nex_ae_user@nex_ae_test`, applied migration
  `2102_ae_agent_context`, passed `9/9` checks, persisted two contiguous context
  generations, verified idempotent/restart reads, and left zero residue.
- AE Slice Gate: `3199 passed`, `5` protected opt-in smoke tests skipped;
  statement coverage `98.48%`, branch coverage `96.51%`.
- Contract validation passed `174` schemas, `236` examples, `204` negative
  examples, and `7` OpenAPI documents.
- Remote providers were available but not called because P5-S2 is a
  deterministic context/reference boundary.

## Deferred

- Capability snapshot and deterministic plan profiles in P5-S3.
- Plan validation and runtime mapping in P5-S4.
- Production Chat/RAG planning-mode wiring and later execution stages.
