# CP-M1-E2E-FX-01B.6B.1A Persistence Decision

## Status

- Date: `2026-11-17`
- Status: `DESIGN_CLOSED_IMPLEMENTATION_REQUIRED`
- Runtime code changed: no
- Database migration executed: no
- Database contacted: no
- Remote provider contacted: no
- Successor: `CP-M1-E2E-FX-01B.6B.2`

## Decision

The existing AE wait, external event inbox, RuntimeJob, and worker mechanics
will be generalized as the single Agent Runtime resume primitive.

Product Preparation will add only:

- immutable `ae_product_prep_checkpoint` history;
- `ae_product_prep_wait_binding`; and
- `ae_product_prep_event_binding`.

It will not add a second wait state machine, event inbox, job queue, daemon,
or Product-specific worker.

## Compatibility Boundary

Existing WorkResult and NSL behavior remains active and compatible. Current
typed columns, constraints, handlers, and tests are preserved while generic
`resume_target_kind`, `wait_contract_ref`, and `event_family` projections are
introduced and backfilled.

Normalization of the existing WorkResult and NSL typed columns into separate
binding tables is deferred. Product Preparation cannot populate or reinterpret
those columns.

## Runtime Resume Decision

`RESUME_EXECUTION` is retained and generalized to resume an AgentExecution
from a persisted wait. Routing uses the wait's target kind:

```text
EXECUTABLE_STEP      -> existing step resume handler
PRODUCT_COORDINATOR  -> generic coordinator resume handler
```

RuntimeJob carries references only. It is not checkpoint or approval
authority.

## Authorized Successor Scope

One bounded AE migration after `2516` is authorized for `6B.2`, recommended
as `2517_ae_product_preparation_resume`. It may generalize the existing wait
and inbox and create the three Product Preparation structures above.

No WC, OA, EOS, or WA migration is authorized. M1 remains `CONTRACT_ONLY`
until actual PostgreSQL compatibility, replay, restart, ACK-loss, and
cross-scope regression pass.

## Verification

- Focused documentation/source contract tests: `7 passed`
- Related 6B.1 and parent-contract regression: `31 passed`
- AE Slice Gate: `6531 passed`, `47 skipped`
- AE statement coverage: `96.45%` (threshold `95.00%`)
- AE branch coverage: `94.65%` (threshold `94.00%`)
- Contract validation: `PASS`
- AE coverage ownership: `PASS`
- Source-backed existing wait constraint: confirmed
- Source-backed existing inbox constraint: confirmed
- Source-backed current `RESUME_EXECUTION` step requirement: confirmed
- Runtime code or schema mutation: none

Machine-readable coverage evidence is written to:

```text
reports/quality/mybee-w70-cp-m1-e2e-fx-01b6b1a-ae-slice-gate.json
```

## Canonical Document

The complete decision is recorded in:

```text
docs/transition/MyBee_Phase1/
NeX_MyBee_CP_M1_E2E_FX_01B_6B_1A_Durable_Product_Preparation_Checkpoint_and_Approval_Event_Persistence_Decision_v1.0.md
```
