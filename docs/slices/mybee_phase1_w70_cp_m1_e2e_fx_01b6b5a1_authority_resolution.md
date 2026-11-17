# CP-M1-E2E-FX-01B.6B.5A.1 Canonical Product Authority Resolution Contract

## Status

- Date: `2026-11-18`
- Status: `CLOSED`
- Parent amendment:
  `NeX_MyBee_CP_M1_E2E_FX_01B_6B_5A_Installed_Product_Coordinator_Authority_and_Dispatch_Closure_v1.0.md`
- Database migration: none
- Remote provider: not required
- Next Slice: `CP-M1-E2E-FX-01B.6B.5A.2`

## Decision

EOS is the canonical product authority resolver for installed M1 transaction
preparation. AE does not infer company, Project, account, period, approval
policy, or Project authority from fixtures, environment defaults, or direct
database access.

The protected operation is
`FINANCE.TRANSACTION_PREPARATION_AUTHORITY.RESOLVE` at
`POST /internal/v2/finance/transaction-preparation-authority:resolve`.
It is side-effect free and accepts only a hash-bound business context,
caller-provided company selector, one to twelve Project Codes, amount,
currency, recognition date, semantic account keys, and exact installed
capability/coordinator lineage.

## EOS Authority Boundary

`EosTransactionPreparationAuthorityService` resolves authority only from
existing product sources:

- active and effective `LegalEntity` by code, name, or exact code-or-name;
- active Projects and their effective company bindings;
- fresh OA authorization for every requested Project;
- debit and credit accounts through the existing semantic COA resolver;
- the OPEN AccountingPeriod covering the recognition date; and
- active, risk-neutral BUSINESS_FORMAL policies for document signoff and
  accounting posting.

The response carries immutable Project, account, policy, period, company, and
OA evidence hashes plus one deterministic resolution hash. Ambiguity,
cross-company scope, inactive or missing authority, revoked Project access,
closed periods, malformed hashes, and source unavailability fail closed. No
business mutation or fallback selection is available.

## Strict AE Consumer

`HttpM1PreparationAuthoritySource` is an installed AE-to-EOS consumer. It
builds the canonical request from the admitted WorkIntent business context,
AgentContext, capability snapshot, coordinator registration, and execution
lineage. It admits only the exact response schema and verifies request,
resolution, authority, evidence, Project order, semantic account, OPEN period,
tenant, subject, capability, coordinator, and correlation bindings before
returning the typed `M1PreparationAuthority`.

The consumer contains no tenant dictionary, fixed company or Project,
default account, policy ID, ratio, amount, date, or scenario-specific fixture.

## Contract Lineage Reconciliation

Adding the EOS operation changed the admitted OpenAPI digest. The dependent
W70 chain was therefore regenerated through the canonical builders:

1. tool contract admission and MyBee platform lock;
2. D04/D12 Skill Pack manifests;
3. candidate bundle and Product Capability Registry locks;
4. Golden A quarantine/activation verification artifacts; and
5. the W70 Foundation Gate receipt.

No Skill business semantics or runtime selector changed. The repository
continues to reject stale source digests.

## Verification

- focused EOS/AE authority contract and client tests: `23 passed`
- immutable-chain and installed-runtime reconciliation: `267 passed`
- contract validation: `274 schemas`, `320 examples`, `260 negative examples`,
  `10 OpenAPI`
- EOS Slice Gate: `2312 passed`, `67 skipped`
  - statement coverage: `96.83%`
  - branch coverage: `94.85%`
- AE Slice Gate: `6667 passed`, `51 skipped`
  - statement coverage: `96.37%`
  - branch coverage: `94.62%`
- W70 Foundation, ownership, Golden Journey transition, and demo/product
  dependency audits: PASS
- lint and import/export ordering: PASS
- evidence:
  - `reports/quality/mybee-w70-cp-m1-01b6b5a1-eos-slice-gate.json`
  - `reports/quality/mybee-w70-cp-m1-01b6b5a1-ae-slice-gate.json`

Protected actual PostgreSQL authority resolution and restart/replay evidence
remain assigned to `.5A.5`. This Slice adds no persistence schema and does not
need embedding, reranking, or generation providers.

## Closure

`CP-M1-E2E-FX-01B.6B.5A.1` is closed. The installed product now has a
canonical, provider-neutral, source-backed authority contract that later
dispatcher composition can consume without introducing a Golden-scenario
fixture path.
