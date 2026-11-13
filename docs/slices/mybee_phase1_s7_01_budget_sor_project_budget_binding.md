# Slice S7-01: Budget SoR and Project Budget Binding

## Objective

Establish NeX-EOS as the authoritative Budget source of record and bind approved
Budget revisions to active Projects without introducing editable actual or
projection values. D04 owns monetary authority; D12 consumes approved Budget
revisions through a read-only Project binding.

## Delivered Boundary

- Added immutable, versioned `eos_budget` records for approved amount, currency,
  category, optional account, and approval/source lineage.
- Added `eos_project_budget_binding` for amount-limit or percentage allocation to
  an approved Project, Budget revision, and D12 WorkCodeSet revision.
- Required exact `BUSINESS_FORMAL` approval proof and fresh OA authorization for
  both Budget commit and Project binding.
- Reused EOS business transaction, idempotency, and outbox infrastructure.
- Required LegalEntity functional currency, active optional Account, approved
  Project-company binding, eligible Project lifecycle, and approved D12 revision.
- Enforced a single allocation mode per Budget revision and aggregate limits of
  Budget amount or 100 percent.
- Exposed owner-scoped internal command/read APIs and canonical OpenAPI entries.
- Kept actual, allocated-actual, forecast, and remaining-budget calculations out
  of this Slice; those remain derived read models for later W50 work.

## Persistence

- Migration: `2542_eos_budget_project_binding.sql`
- Tables: `eos_budget`, `eos_project_budget_binding`
- Budget identity: `(tenant_id, budget_id, budget_version)`
- Binding identity: `(tenant_id, binding_id)` with immutable semantic replay

## Verification

- Focused unit suite passed `50` tests and covers acceptance, replay,
  authorization and approval denial, currency/account/project/WorkCodeSet
  rejection, allocation-mode conflict, aggregate amount/percentage limits,
  malformed contracts, and API admission/error projection. Focused coverage for
  the three new runtime modules is statement/branch `92%` overall; the API module
  is `100%`.
- Actual PostgreSQL protected smoke ran against `nex_eos_test` in an isolated
  schema, applied the complete EOS migration inventory through `2542`, committed
  and read back a Budget and Project binding, verified exact replay and row
  counts, and removed the schema after completion: `1 passed` in `3.45s`.
- Final NeX-EOS Slice Gate passed all `5/5` commands with `1,959 passed` and
  `57` explicit protected skips. Statement coverage is `96.81%`; branch coverage
  is `95.02%`.
- Contract validation passed for `263` schemas, `315` examples, `257` negative
  examples, and `10` OpenAPI documents. Golden Journey transition and
  demo/product dependency audits both passed with zero findings.
- Remote model providers are not part of this deterministic accounting boundary.

## Operational Decision

Budget monetary authority remains in EOS D04. Project planning D12 may reference
an approved Budget revision but cannot mutate its approved amount or currency.
All later actual and projection values must be derived from posted GL and
allocation lineage, never written into the Budget SoR as operator-editable state.
