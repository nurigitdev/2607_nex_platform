# P5-S1 WorkIntent and Prompt Registry Hardening

## Scope

- Implement the P5 v1.1 WorkIntent adapter and immutable persistence boundary.
- Preserve the existing AE `IntentDecision` as the compatibility input without
  changing the current Chat/RAG user-visible flow.
- Add one shared semantic SHA-256 utility that distinguishes legacy bare
  digests from P5 `sha256:<64 hex>` hash references without double hashing.
- Harden prompt template versions as immutable insert-or-verify records.
- Make prompt binding history insertion and pointer activation one atomic
  compare-and-set transaction with exact prompt provenance lookup.

## Decisions

- `NEX_AE_PLANNING_MODE` accepts only `disabled`, `shadow`, or `required` and
  defaults to `disabled`. P5-S1 establishes this rollout contract but does not
  yet route the production Chat/RAG path through WorkIntent planning.
- WorkIntent stores project-neutral semantic intent only. It does not add a
  Project, Project Agent, WC, NSL, WRITE, or provider execution boundary.
- WorkIntent identity is `(tenant_id, work_intent_id)`, while
  `(tenant_id, agent_execution_id, intent_revision)` prevents two records from
  owning the same execution revision. Revisions must form a contiguous chain.
- Prompt startup seeding is insert-only for bindings and cannot move an
  operator-managed pointer backward. Runtime activation locks the binding on
  PostgreSQL, verifies the expected current version, inserts history, and
  updates the pointer in the same transaction.
- WorkIntent and prompt provenance persist hashes, references, policy labels,
  and model identifiers; they do not persist the raw private user prompt.

## Persistence

- `2100_ae_prompt_registry_hardening.sql` adds
  `ae_prompt_binding_history` and its correlation/time indexes.
- `2101_ae_work_intent.sql` adds the immutable revisioned
  `ae_work_intent` table with AgentExecution and revision-chain constraints.
- Both table names and constraint/index names remain within PostgreSQL naming
  limits.

## Verification

- Focused P5-S1 regression: `71 passed`.
- Changed-module coverage: semantic hash, prompt persistence, and WorkIntent
  each reached `100%` statement and `100%` branch coverage.
- Actual PostgreSQL smoke used `nex_ae_user@nex_ae_test`, confirmed migration
  inventory through `2101_ae_work_intent`, executed `8/8` checks, persisted one
  binding-history row and one WorkIntent row, verified restart/idempotent reads,
  and completed cleanup with zero residue.
- AE Slice Gate: `3150 passed`, `5` protected opt-in smoke tests skipped;
  statement coverage `98.46%`, branch coverage `96.46%`.
- Contract validation passed `174` schemas, `236` examples, `204` negative
  examples, and `7` OpenAPI documents.
- Remote generation, embedding, and reranker providers were available but were
  not called because provider execution is outside P5-S1.

## Deferred

- Production Chat/RAG admission wiring for shadow/required planning modes.
- AgentContext generation and trusted context resolver integration in P5-S2.
- Capability snapshots, plan generation/validation, deterministic compilation,
  multi-step execution, and plan-level finalization in later P5 Slices.
