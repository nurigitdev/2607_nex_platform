# CP-M1-E2E-FX-01B.2 Durable WorkIntent Business Context Admission

## Status

- Date: `2026-11-16`
- Status: `CLOSED`
- Parent work order:
  `NeX_MyBee_CP_M1_E2E_FX_01B_Durable_Business_Context_and_M1_Transaction_Orchestration_Closure_v1.0.md`
- Entry commit: `90cfda87`
- Database migration: none
- Remote provider: not required
- Checkpoint Gate: deferred until `CP-M1-E2E-FX-01B.3`
- Next Slice: `CP-M1-E2E-FX-01B.3`

This Slice activates the admitted `ae.business_request_context.v1` contract
inside durable `WorkIntent v1.2` records for the M1 finance intent. It does not
yet activate `DelegationSpec v1.2`, claimed planning source v2, transaction
orchestration, or governed execution.

## Runtime Admission

The active intent prompt is advanced from v9 to v10. For
`FINANCE.VOUCHER.APPROVE_AND_POST`, the admitted candidate must contain one
unambiguous Project code and the canonical M1 business fields:

- company selector;
- document subject;
- counterparty selector;
- amount and ISO currency;
- recognition date;
- description; and
- zero or more contiguous Project allocation code/ratio pairs.

The admission boundary canonicalizes amount, ratio, currency, date, and
Project-code representations before hashing. Allocation ratios must total
exactly `1.000000`. Malformed decimal/date/currency values, ambiguous Projects,
authority-bearing fields, sparse allocation indexes, duplicate allocation
Projects, oversized input, and semantic-hash tampering fail closed.

The resulting `WorkIntent v1.2` persists:

- normalized typed business context;
- candidate, source-interaction, and model provenance;
- candidate and context semantic hashes;
- the admitted completion contract; and
- an explicit constraint that authority remains with owner services.

Raw prompts and hidden model reasoning are not persisted in the business
context. Tenant, requester, Project UUID, OA authority, account resolution,
FX/period facts, approval proof, Candidate identity, and Posting outcome are
not accepted as model-provided authority.

## Compatibility and Replay

`WorkIntent v1.1` remains the installed schema for non-M1 intents and for
historical replay. It is neither rewritten nor silently upgraded. Only the
M1 finance intent with an admitted candidate can produce v1.2.

Repository validation accepts both versions and verifies the full v1.2
context, provenance, and semantic hashes on read. Different valid business
requests produce different context and WorkIntent hashes. Persistence round
trips preserve the exact admitted JSON.

The project-delegation activator now preserves an intact v1.2 context while
adding the existing Project authority constraint. The v1.1 behavior remains
unchanged.

## Repository Reconciliation

Golden A quarantine checks now recognize the active v10 prompt and require
the new context metadata. AE coverage ownership inventory counts were updated
from the repository source inventory after adding the new active product
module; coverage thresholds were not reduced.

## Verification

- Focused business-context regression: `65 passed`
- Focused affected regression: `187 passed`
- New module coverage:
  - statement `99.06%`
  - branch `99.23%`
- Canonical AE Slice Gate: `6/6` commands passed
- AE regression: `6310 passed`, `46 skipped`
- Aggregate AE coverage:
  - statement `96.46%`
  - branch `94.69%`
- Active-product coverage:
  - statement `97.14%`
  - branch `95.01%`
- Contract validation:
  `269 schemas`, `319 examples`, `260 negative examples`, `10 OpenAPI`
- Golden Journey transition audit: pass
- Demo/product dependency audit: pass
- AE ownership/quarantine audit: pass, zero conflicts
- Ruff and `git diff --check`: pass

The ordinary Slice Gate protected skips are the existing opt-in PostgreSQL,
RustFS, Playwright, and live-provider suites. This Slice changes no relational
schema and requires no protected database or provider execution.

## Closure Decision

`CP-M1-E2E-FX-01B.2` is closed. Typed M1 business input is now admitted,
hash-bound, and durable in WorkIntent without granting model authority or
breaking v1.1 replay. `CP-M1-E2E-FX-01B.3` may activate exact context
propagation across AE-to-WC delegation and claimed background planning; its
completion remains the planned PostgreSQL and Checkpoint boundary.
