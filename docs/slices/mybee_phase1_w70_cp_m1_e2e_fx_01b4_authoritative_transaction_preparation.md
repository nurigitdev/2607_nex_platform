# CP-M1-E2E-FX-01B.4 Authoritative Transaction Preparation And Approval

## Status

- Date: `2026-11-16`
- Status: `CLOSED`
- Parent work order:
  `NeX_MyBee_CP_M1_E2E_FX_01B_Durable_Business_Context_and_M1_Transaction_Orchestration_Closure_v1.0.md`
- Entry commit: `26627764`
- Database migration: none
- Remote provider: not required
- Next Slice: `CP-M1-E2E-FX-01B.5`

This Slice turns the durable M1 business context into an installed,
registry-selected transaction-preparation flow. It does not post a Journal or
write an allocation. Owner services remain authoritative for company,
Project, Account, approval, and accounting-proof facts.

## Installed Preparation Boundary

The active AE product runtime now installs
`MYBEE.M1.AUTHORITATIVE_TRANSACTION_PREPARATION` from a hash-admitted registry.
The adapter composes the existing EOS business-approval and VoucherCandidate
clients; it does not create a parallel approval engine or accounting store.

Preparation advances through three restart-safe, hash-bound checkpoints:

1. `WAITING_BUSINESS_APPROVAL` after proposal submission;
2. `WAITING_ACCOUNTING_APPROVAL` after final ApprovedDocumentEnvelope,
   Candidate creation and validation, and accounting-review submission; and
3. `READY_FOR_D04` only after immutable review submission and fresh EOS
   posting admission backed by the final accounting proof.

The preparation hash binds the admitted business-context hash, registry
identity, deterministic operation and idempotency identities, exact authority
projection, and owner-service references. Same execution and semantics replay
the same identities. Changed request semantics conflict instead of producing
a second financial preparation.

## Authority Admission

The preparation boundary accepts owner-service projections, not model
authority. It validates and hashes:

- EOS company identity, version, functional currency, and evidence hash;
- every requested EOS Project identity and version;
- a fresh OA decision reference, revision hash, and source version for every
  requested Project;
- EOS semantic debit and credit Account identities and evidence hashes;
- BUSINESS_FORMAL and accounting approval policy IDs, versions, and hashes;
- requester, tenant, effective time, and aggregate authorization lineage.

The Project and authorization sets must exactly equal the context allocation
set. Missing, extra, stale, malformed, cross-context, or wrong-semantic
authority fails before provider mutation. Accounting continuation also fails
unless the immutable Candidate review timeline contains its `SUBMIT` event.

The existing EOS Project resolution, EOS semantic Account resolution, OA
Project authorization, WC human approval, and EOS accounting-proof APIs remain
the sources of truth. No direct business fixture, historical Golden A binding,
or new relational table is introduced.

## Product and Compatibility Boundaries

The preparation runtime is composed by the canonical AE product profile and
included in installed runtime readiness. Historical Golden A pinned files were
not modified. During implementation the quarantine Gate correctly detected an
attempted historical-file drift; the changes were removed and the integration
was placed in the active product runtime. The MyBee runtime ownership inventory
now explicitly includes the new active preparation runtime.

## Verification

- Focused preparation and consumer regression: `107 passed`
- Focused new-module coverage:
  - aggregate statement/branch coverage: `98%`
  - preparation orchestration: `99%`
  - VoucherCandidate client: `98%`
  - installed preparation runtime: `96%`
- Actual OA/WC/EOS/AE PostgreSQL protected smoke: `6 passed`, no skip
  - AE/WC context persistence and restart replay;
  - EOS ApprovedDocumentEnvelope proof binding and zero residue;
  - EOS Candidate review state and immutability;
  - EOS fresh-OA accounting-proof posting admission;
  - EOS-to-OA entitlement replay and zero residue; and
  - OA/WC human authorization and decision Gate.
- Canonical AE Slice Gate: `6/6` commands passed
- AE regression: `6452 passed`, `47 skipped`
- Aggregate AE coverage:
  - statement `96.47%`
  - branch `94.74%`
- Active-product coverage:
  - statement `97.14%`
  - branch `95.06%`
- Contract validation:
  `269 schemas`, `319 examples`, `260 negative examples`, `10 OpenAPI`
- Golden journey, demo/product dependency, ownership, and quarantine audits:
  pass
- Ruff and `git diff --check`: pass

The ordinary Slice Gate skips are existing opt-in protected suites. The six
Slice-specific database cases were run separately against the actual test
databases with their protection flags enabled.

## Closure Decision

`CP-M1-E2E-FX-01B.4` is closed. Durable M1 context can now produce an
authority-bound proposal, ApprovedDocumentEnvelope, VoucherCandidate,
accounting-review checkpoint, and final posting-admission checkpoint without
granting authority to a model or compatibility fixture. `.5` may materialize
the deterministic D12/D04 plan from these exact owner-service results.
