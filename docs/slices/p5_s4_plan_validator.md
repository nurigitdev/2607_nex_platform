# P5-S4 Plan Validator

## Scope

- Validate P5 AgentPlan records deterministically without an LLM or remote
  provider call.
- Persist immutable PlanValidationResult v1.1 records with exact AgentPlan and
  AgentContext lineage.
- Apply the CA01A validation status to AgentExecution state/phase mapping
  atomically with validation persistence.

## Decisions

- The validator checks exact WorkIntent, AgentContext, and Capability Snapshot
  references before granting compile authority.
- It validates clarification state, required entity resolution, context
  conflicts/degradations, DAG uniqueness/dependencies/cycles, terminal criteria,
  step-output/report bindings, exact capability versions, allowed step types,
  and output contracts.
- Future schema vocabulary remains representable. Unsupported `DYNAMIC`,
  `CERTIFIED_BINDING`, or `DELEGATE_WORK` paths are blocked explicitly rather
  than mistaken for current runtime availability.
- The seven status mappings are fixed:

| Status | Directive | AgentExecution state | Phase | Compile |
|---|---|---|---|---|
| `VALID` | `PROCEED_TO_COMPILE` | `RUNNING` | `PLAN_COMPILE` | yes |
| `CLARIFICATION_REQUIRED` | `WAIT_FOR_INPUT` | `WAITING_INPUT` | `PLAN_VALIDATE` | no |
| `REPLAN_REQUIRED` | `BLOCK_REPLAN_REQUIRED` | `BLOCKED` | `PLAN_VALIDATE` | no |
| `CONTEXT_REFRESH_REQUIRED` | `BLOCK_CONTEXT_REFRESH_REQUIRED` | `BLOCKED` | `PLAN_VALIDATE` | no |
| `BLOCKED` | `BLOCK_EXECUTION` | `BLOCKED` | `PLAN_VALIDATE` | no |
| `INVALID_TERMINAL` | `FAIL_VALIDATION` | `FAILED` | `PLAN_VALIDATE` | no |
| `RETRYABLE_VALIDATION_FAILURE` | `RETRY_VALIDATION_BOUNDED` | `RUNNING` | `PLAN_VALIDATE` | no |

- `max_auto_replan = 0`. Technical retry reuses the same AgentPlan; no status
  invokes semantic replanning or context-refresh loops automatically.

## Persistence

- P5-S4 uses the `ae_plan_validation` table reserved by migration
  `2103_ae_capability_plan_validation.sql`.
- Insert-or-verify validation persistence and AgentExecution version-CAS
  transition execute in one database transaction.
- Replaying the same validation result is idempotent and does not advance the
  execution version twice.
- A stale execution version rolls back the new validation row.

## Verification

- Focused validator regression: `117 passed`; AgentPlan and PlanValidation
  modules reached combined statement/branch coverage of `99%`.
- All seven status/directive/state/phase mappings were tested, including zero
  compile authority for every non-`VALID` result and zero automatic replan.
- Actual PostgreSQL smoke used `nex_ae_user@nex_ae_test` and passed `11/11`
  checks. It persisted a real validation row, atomically moved AgentExecution
  to `RUNNING / PLAN_COMPILE`, verified restart/idempotency, found zero compile
  rows, and left zero residue.
- AE Slice Gate: `3338 passed`, `5` protected opt-in smoke tests skipped;
  statement coverage `98.52%`, branch coverage `96.63%`.
- Contract validation passed `174` schemas, `236` examples, `204` negative
  examples, and `7` OpenAPI documents.
- Remote providers were available but not called because validation is a local,
  deterministic authority boundary.

## Deferred

- P5-S5 consumes only `VALID / PROCEED_TO_COMPILE` results and creates the
  deterministic ExecutablePlan.
- Bounded retry orchestration uses the existing runtime retry policy in a later
  integration slice; S4 only fixes and persists its authority mapping.
