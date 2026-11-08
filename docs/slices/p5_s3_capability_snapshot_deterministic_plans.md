# P5-S3 Capability Snapshot and Deterministic Plans

## Scope

- Persist a tenant-scoped immutable Capability Catalog Snapshot with exact
  capability versions.
- Build immutable P5 v1.1 AgentPlan records from the persisted WorkIntent,
  AgentContext, and Capability Snapshot lineage.
- Support only the approved deterministic `DIRECT` and `KNOWN_TEMPLATE`
  profiles. Dynamic or LLM planning remains unavailable in P5.

## Decisions

- The initial exact capability set is `AE.CHAT.COMPATIBILITY@p5.1` and
  `AE.RESULT.REPORT@p5.1`.
- There is no implicit `latest` lookup. A missing exact version fails closed.
- The physical snapshot table is `ae_capability_snapshot`; it represents the
  logical Capability Catalog Snapshot while keeping database identifiers
  concise.
- Planning is project-neutral and serial: maximum 12 steps, delegation depth
  zero, parallelism one, and no automatic semantic replan.
- Profile mappings are deterministic:
  - `GENERAL_ANSWER` -> one-step `DIRECT` compatibility plan.
  - `GROUNDED_ANSWER` -> compatibility step plus interactive report.
  - `DOCUMENT_SUMMARY` -> compatibility step plus interactive report.
  - `DOCUMENT_GENERATION` -> compatibility step plus artifact report.
- AgentPlan cannot execute directly. P5-S4 validation and P5-S5 compilation
  remain mandatory boundaries.

## Persistence

- `2103_ae_capability_plan_validation.sql` adds
  `ae_capability_snapshot`, `ae_agent_plan`, and the reserved
  `ae_plan_validation` table used by P5-S4.
- Snapshot versions are unique per tenant. Plan versions are unique and
  contiguous per AgentExecution.
- AgentPlan persistence verifies exact WorkIntent revision/hash, AgentContext
  generation/hash, and Capability Snapshot version/hash before insertion.
- Snapshot and plan writes use immutable insert-or-verify semantics and are
  restart-readable.
- All new table, constraint, and index names fit PostgreSQL's 63-byte limit.

## Verification

- Focused P5-S1..P5-S3 regression: `191 passed`.
- WorkIntent, AgentContext, Capability Snapshot, and AgentPlan modules reached
  combined statement/branch coverage above `99%`; the two new S3 modules
  reached `99%` combined coverage.
- Actual PostgreSQL smoke used `nex_ae_user@nex_ae_test`, confirmed migration
  `2103_ae_capability_plan_validation`, and passed `10/10` checks.
- The smoke persisted one capability snapshot and four plans, verified all
  four deterministic profiles, immutable idempotency, restart reads, exact
  version lineage, trusted resolver call count, privacy, and zero residue.
- AE Slice Gate: `3284 passed`, `5` protected opt-in smoke tests skipped;
  statement coverage `98.51%`, branch coverage `96.60%`.
- Contract validation passed `174` schemas, `236` examples, `204` negative
  examples, and `7` OpenAPI documents.
- Remote providers were available but not called because P5-S3 is a fully
  deterministic planning and persistence boundary.

## Deferred

- All seven PlanValidation statuses and exact runtime mapping in P5-S4.
- Deterministic compilation and executable plan identity mapping in P5-S5.
- Production Chat/RAG planning-mode wiring and execution remain in later P5
  slices.
