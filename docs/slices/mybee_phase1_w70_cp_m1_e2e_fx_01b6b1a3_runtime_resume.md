# CP-M1-E2E-FX-01B.6B.1A.3 Runtime Event Matching and Resume Routing

## Status

- Date: `2026-11-17`
- Status: `IMPLEMENTED_AND_VERIFIED`
- Migration: none; reuses migration `2517`
- Actual database: `nex_ae_test`
- Remote provider contacted: no
- Successor: `CP-M1-E2E-FX-01B.6B.1A.4`

## Implemented Boundary

This Slice generalizes runtime event matching, wait satisfaction, and
`RESUME_EXECUTION` routing over the shared wait/event envelopes delivered by
`6B.1A.1` and `6B.1A.2`.

- `RuntimeEventMatcher` atomically schedules one resume job, moves a wait from
  `PENDING` to `RESUME_QUEUED`, and moves its event from `RECEIVED` to
  `MATCHED`.
- Exact replay returns the original job and persisted `run_after`; missing or
  drifted replay authority fails closed.
- `RESUME_EXECUTION` now distinguishes `EXECUTABLE_STEP` and
  `PRODUCT_COORDINATOR` targets. Step targets require an executable step;
  Product Coordinator targets prohibit one.
- Product Preparation resumes carry only checkpoint, coordinator, wait, and
  event references. Business payload is not copied into the runtime job.
- `SqlAlchemyResumeRouteSource` resolves a queued route from persisted wait
  authority and verifies typed Product binding and payload lineage.
- `ResumeTargetHandlerRegistry` provides target-dispatched handler selection
  without installing or activating a Product worker.
- Existing WorkResult and NSL approval services retain their domain-specific
  validation and use the shared matcher only for the common atomic transition.
- Dispatcher reconciliation recognizes a valid step-less Product Coordinator
  resume as pending work rather than malformed work. With no Product handler
  registered, the job remains `QUEUED` and observable.

M1 remains `CONTRACT_ONLY`. This Slice does not activate Product Preparation
orchestration, invoke a provider, or execute a business mutation.

## Runtime Invariants

1. A matched event, satisfied wait, and resume job commit in one transaction.
2. A replay cannot create a second job or change the original scheduling time.
3. Wait, event, execution, step, target, checkpoint, and coordinator lineage
   must agree before routing.
4. Product Coordinator routes require a complete typed binding; a generic
   Product-shaped envelope alone is insufficient.
5. WorkResult and NSL approval contracts remain active compatibility paths and
   are not replaced or retired by the generalized primitive.
6. Invalid target/step combinations fail at job admission.
7. No new table, migration, queue, daemon, or worker is introduced.

## Verification

- focused generalized resume and compatibility regression: `172 passed`
- runtime-job target admission regression: `28 passed`
- new `runtime_resume` module coverage: statement `100%`, branch `100%`
- actual `nex_ae_test` replay/restart smoke: `2 passed`
- PostgreSQL rollback residue: `0`
- AE Slice Gate: `6593 passed, 50 skipped`
- AE statement coverage: `96.40%` (threshold `95.00%`)
- AE branch coverage: `94.66%` (threshold `94.00%`)
- AE product ownership coverage: statement `97.05%`, branch `94.97%`
- contract validation: `PASS`
- golden-journey transition audit: `PASS`
- demo/product dependency audit: `PASS`
- AE coverage ownership: `PASS`, active graph `96`, conflicts `0`

Machine-readable Gate evidence:

```text
reports/quality/
mybee-w70-cp-m1-e2e-fx-01b6b1a3-ae-slice-gate.json
```

## Remaining Boundary

`6B.1A.4` may connect a registered Product Coordinator handler to this shared
resume route. It must reuse the existing runtime worker and scheduler, keep
the typed checkpoint as authority, and preserve WorkResult/NSL compatibility.
Until that activation Slice closes, Product Coordinator resume jobs remain
durable and queued rather than being executed.
