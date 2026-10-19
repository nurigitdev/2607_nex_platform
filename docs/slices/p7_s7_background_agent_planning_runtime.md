# P7-S7: Background Agent Planning + Existing Runtime Integration

## Status

Completed on 2026-10-19. P7-S8 is authorized.

## Goal

Run claimed CA/PA/EA work through the existing P5/P6.5 semantic planning and
P6 execution runtime without creating another planner, queue, or worker stack.

```text
WC committed Claim + bounded planning source
-> AE CLAIMED_WORKITEM AgentExecution
-> existing INTENT / CONTEXT / PLAN admission
-> existing compiler and RuntimeJob worker
-> LOCAL_SKILL / NSL READ / deterministic report
-> AgentResult
-> WC WorkResult exact ACK
-> child success and parent resume
```

## Boundary Decisions

- The Frozen `ClaimExecutionHandoff` remains byte-for-byte unchanged and is
  still the sole Claim, Assignment, lease, and execution authority.
- WC transports a separate bounded `ClaimedWorkPlanningEnvelope` projection.
  It carries the WorkItem goal, class, project, capability, artifact, and
  evidence references needed for planning, but grants no authority.
- AE persists that projection in `ae_claim_handoff_inbox` and reloads it by
  the admitted child execution. Migration `2405_ae_claimed_planning_source`
  adds only the nullable JSONB source column for historical-row safety.
- `BackgroundAgentPlanningService` adapts a claimed execution to the existing
  deterministic semantic admission service. Existing WorkIntent,
  AgentContext, AgentPlan, PlanValidation, ExecutablePlan, RuntimeJob,
  StepResult, AgentResult, and ResultDelivery records remain the systems of
  record.
- Compatibility workspace, conversation, and interaction UUIDs are stable
  derivations used only where the pre-P7 persistence layout still requires
  them. They do not convert background work into an IA prompt.
- Provider output remains a candidate. It cannot choose the agent, Claim,
  Assignment, project authority, execution identity, or WC result authority.
- A claimed child is not successful when its AgentResult is merely persisted.
  The existing result publication boundary requires an exact WC WorkResult
  acknowledgement before moving the child to `SUCCEEDED`; the WC event inbox
  then creates the existing `RESUME_EXECUTION` job for the parent.

## Implementation

- Generalized the P5/P6.5 intent, context, candidate admission, validation,
  compilation, finalization, and result builders for IA and project-scoped
  CA/PA/EA executions while preserving IA compatibility.
- Added fail-closed lineage checks across tenant, agent, execution, WorkItem,
  project, planning source, plan, result, and delivery identities.
- Kept `nex_runtime.JobQueue` as the shared technical queue library and reused
  the existing AE RuntimeJob worker. No P7-specific generic queue was added.
- Added restart-safe and idempotent result publication from the actual claimed
  AgentResult to the Frozen WC WorkResult contract.
- Updated historical smoke inventory checks to calculate or verify the current
  additive migration set instead of freezing obsolete migration counts.

## Live Evidence

The protected P7-S7 journey used the actual local `nex_ae_test` and
`nex_wc_test` PostgreSQL databases, the live DGX generation provider, and the
admitted in-process NSL v0.1 READ backend.

```text
AE migration        = 2405_ae_claimed_planning_source
WC migration        = 1002_wc_work_result
provider model      = Qwen3.5-4B
semantic stages     = INTENT, CONTEXT, PLAN
runtime jobs        = 3
runtime attempts    = 3
step results        = 2
AgentResult         = 1
ResultDelivery      = 1
WC WorkResult       = 1
checks              = 43 / 43
owned residue       = 0
```

The live path compiled `LOCAL_SKILL` plus `DETERMINISTIC_REPORT`, executed the
source-backed NSL READ, preserved provider and S/E/UUID lineage, replayed WC
publication idempotently, accepted the result event once, and resumed the
parent only after the exact WC acknowledgement.

Sanitized evidence is stored in
`reports/live/p7-s7-background-planning-postgres-live.json`.

## Verification

- Focused P7-S7 and affected compatibility tests: PASS.
- WC Slice Gate: `173 passed`; statement `96.67%`, branch `94.23%`.
- AE Slice Gate: `4527 passed`, `11 skipped`; statement `98.32%`, branch
  `96.23%`.
- Contract validation: schemas `174`, examples `236`, negative examples `204`,
  OpenAPI documents `8`.
- Protected PostgreSQL + live provider E2E: PASS, `43/43` checks, zero owned
  residue.

The 11 skipped AE tests are separately protected historical smoke suites with
their own opt-in flags. P7-S7's actual PostgreSQL and remote-provider journey
was explicitly enabled and passed outside the ordinary regression Gate.
