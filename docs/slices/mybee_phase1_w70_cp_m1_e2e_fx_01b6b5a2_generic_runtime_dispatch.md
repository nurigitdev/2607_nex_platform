# CP-M1-E2E-FX-01B.6B.5A.2 Generic Runtime Assignment And Dispatch

## Status

- Date: `2026-11-18`
- Status: `CLOSED`
- Parent amendment:
  `NeX_MyBee_CP_M1_E2E_FX_01B_6B_5A_Installed_Product_Coordinator_Authority_and_Dispatch_Closure_v1.0.md`
- Database migration: none
- Remote provider: not required
- Next Slice: `CP-M1-E2E-FX-01B.6B.5A.3`

## Decision

The installed AE worker keeps one RuntimeJob queue, dispatcher, lease, attempt,
heartbeat, retry, and fairness lifecycle. It now recognizes two generic
assignment kinds:

- `EXECUTABLE_STEP`
- `PRODUCT_COORDINATOR`

`PRODUCT_COORDINATOR` is not an executor kind. It never enters
`P5StepExecutorRegistry`, `step_executors.py`, or the NSL backend-profile
selection path. A separate `RuntimeAssignmentHandlerRegistry` routes assignment
kinds after the shared dispatcher has produced a valid assignment.

## Authoritative Assignment Derivation

No durable column or JSON discriminator was added. A Product assignment is
derived only when an existing RuntimeJob and WaitRegistration have this exact
persisted lineage:

- RuntimeJob type is `RESUME_EXECUTION` and has no `executable_step_id`;
- RuntimeJob `wait_id` resolves in the same tenant;
- wait type is `PRODUCT_PREPARATION`;
- resume target is `PRODUCT_COORDINATOR`;
- wait and RuntimeJob reference the same agent execution;
- wait state is `RESUME_QUEUED`; and
- wait `resume_runtime_job_id` equals the claimed RuntimeJob.

All other step-less or malformed jobs remain governed by the existing
reconciliation policy. Product jobs use the existing atomic claim update,
leadership fencing, lease token, attempt record, retry, and expired-lease
recovery behavior.

## Installed Handler Boundary

The dispatcher accepts only assignment kinds registered by the installed
handler registry. The current installed composition registers
`EXECUTABLE_STEP` only. Therefore a valid Product job is not claimed before
the Product handler is installed in `.5A.3`; it remains `QUEUED` and appears in
the bounded assignment backlog projection without tenant, job, or content
labels.

This preserves fail-closed rollback behavior and avoids a claim that the
current process cannot settle. The generic registry reports a retryable
handler-unavailable error if an already-issued assignment reaches a process
whose handler registration has drifted.

## Compatibility And Coverage Ownership

Existing executable-step callers retain their default assignment kind and
constructor shape. Worker assignment validation now applies step capability
and backend checks only to `EXECUTABLE_STEP`, while Product assignments must be
step-free resume jobs with no executor or backend profile.

The new active product module `runtime_assignment_handlers.py` increased the
source-backed AE active-import inventory from `96` to `97`. The frozen
ownership test was intentionally reconciled to the admitted module; ownership
scopes, coverage floors, and historical quarantine counts were not changed.

## Verification

- focused dispatcher, worker, registry, composition, resume, coordinator,
  activation, and replay/restart regression: `147 passed`
- ownership and focused runtime reconciliation: `89 passed`
- AE Slice Gate: `6679 passed`, `51 skipped`
  - statement coverage: `96.36%`
  - branch coverage: `94.59%`
  - commands: `6/6`
- contract validation: `274 schemas`, `320 examples`, `260 negative examples`,
  `10 OpenAPI`
- AE coverage ownership: `190 modules`, `97 active graph`, `180 product`,
  `5 compatibility`, `5 historical`, no conflicts
- Golden Journey transition and demo/product dependency audits: PASS
- lint, formatting, compile, and diff checks: PASS
- evidence:
  - `reports/quality/mybee-w70-cp-m1-01b6b5a2-ae-slice-gate.json`

Actual AE/EOS/OA/WC PostgreSQL protected acceptance remains assigned to
`.5A.5`. This Slice does not require generation, embedding, or reranking
providers.

## Closure

`CP-M1-E2E-FX-01B.6B.5A.2` is closed. Runtime assignment and dispatch are now
generic across executable steps and Product Coordinator resumes without a
second queue, worker, daemon, fixture authority, or database migration.
`.5A.3` may install the public Product router and Product handler through the
same registry and installed runtime factory.
