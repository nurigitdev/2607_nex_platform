# CP-M1-E2E-FX-01A.3: Installed Claim Handoff Runtime Composition

## Status

- Slice: `CP-M1-E2E-FX-01A.3`
- Status: `CLOSED`
- Database migration: none
- Remote provider: not required

## Decision

The WC `CLAIM_EXECUTION_HANDOFF` endpoint is an installed orchestration
boundary, not admission-only plumbing. A successful response now means that
the existing AE execution was durably admitted, its claimed-work planning
source was compiled through the P5/P6 semantic pipeline, and the first
executable step was scheduled through the shared runtime JobQueue.

The handoff does not receive a separate queue, execution model, or scenario
runner. It composes the existing `AgentExecutionAdmissionService`,
`BackgroundAgentPlanningService`, `DeterministicCandidateAdmissionService`,
`SqlAlchemyMultiStepEngine`, and `SqlAlchemyRuntimeJobQueue`.

## Runtime Semantics

1. WC admission persists the handoff inbox and claimed AgentExecution.
2. Background planning reloads that exact execution and durable planning
   source.
3. Existing semantic stages persist WorkIntent, AgentContext, AgentPlan,
   validation, and ExecutablePlan.
4. The existing multi-step engine schedules the first runnable step.
5. Only then does the API acknowledge the WC delivery.

Retry after a provider, persistence, or scheduling failure reuses the same
event, execution, deterministic plan IDs, semantic evidence, and runtime-job
dedup key. No duplicate execution or plan lineage is introduced.

## Fail-Closed Rules

- Agent Runtime and semantic planning must both be `required`.
- AE persistence, runtime JobQueue, and semantic service must all exist.
- The admitted execution must expose exact tenant and execution identity.
- Planning must return `COMPILED`, the same execution ID, and an executable
  plan ID.
- Background planning and scheduling failures retain their retryability and
  prevent handoff ACK.

## Verification

- focused claim/runtime regression: `59 passed`
- formatter, lint, and diff hygiene: PASS
- AE Slice Gate: PASS
- next boundary: `CP-M1-E2E-FX-01A.4`

