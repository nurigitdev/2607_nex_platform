# UXM-S11 UX State Mapper Completion and Business Terminology

## Outcome

PASS / CLOSED. The S08A mapper now provides the complete canonical work-state
vocabulary for Workspace, progress, result, Approval, artifact, and operation
surfaces. A separate business terminology projection keeps internal platform
terms out of ordinary user-facing copy.

## Canonical Work States

```text
IDLE
ACCEPTING
PLANNING
RUNNING
WAITING_APPROVAL
RESUMING
VERIFYING
SUCCEEDED
PARTIAL
FAILED
CANCELLED
```

The earlier S08A inputs `requested`, `in_progress`, and `completed` remain
accepted as compatibility inputs and resolve to `ACCEPTING`, `RUNNING`, and
`SUCCEEDED`. They are not canonical output values. The strict TypeScript type
guard admits uppercase canonical values only.

## Source Mapping Boundary

The same `src/ux/workState.ts` source maps admitted states from:

```text
AgentExecution
GenerationLifecycle
Approval
ResultDelivery
Artifact
OperationState
```

An unknown source or state fails closed to `UNKNOWN`. It is not inferred as
running and receives no invented percentage or timeline progress. Approval
rejection remains a completed decision with a rejected outcome rather than a
failed Agent execution.

## Business Terminology

`src/ux/terminology.ts` formalizes Korean-default presentation for Workspace,
approval, result files, input readiness, documents, attachments, sources,
business results, and Projects. Unknown terms return the generic `업무 정보`
label without echoing the internal value.

Original enums are hidden by default. A bounded technical-state projection is
available only when an explicit debug flag is enabled; it rejects unsafe or
overlong values.

## Verification

```text
focused state/terminology/Approval tests = PASS, 23 tests
AE Web Node regression                  = PASS, 408 tests
React regression                        = PASS, 78 tests / 16 files
TypeScript typecheck                     = PASS
modern production import audit           = PASS, 21 files
modern browser security audit            = PASS, 22 files
design token consistency                 = PASS, 146 variables / 15 components
React v2 production build                = PASS
PostgreSQL / remote providers             = NOT REQUIRED
```

The main JavaScript bundle is 532.60 kB and retains the known Vite chunk-size
advisory. This Slice adds no database, backend API, or browser route change.

## Decision

```text
UXM-S11 = PASS / CLOSED
UXM-S12 = AUTHORIZED
```
