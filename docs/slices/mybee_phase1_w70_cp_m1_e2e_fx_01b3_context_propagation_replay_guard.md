# CP-M1-E2E-FX-01B.3 Context Propagation and Replay Guard

## Status

- Date: `2026-11-16`
- Status: `CLOSED`
- Parent work order:
  `NeX_MyBee_CP_M1_E2E_FX_01B_Durable_Business_Context_and_M1_Transaction_Orchestration_Closure_v1.0.md`
- Entry commit: `a30fe120`
- Database migration: `2516_ae_m1_work_intent`
- Remote provider: not required
- Checkpoint Gate: passed after this Slice
- Next Slice: `CP-M1-E2E-FX-01B.4`

This Slice propagates the admitted M1 business context without semantic
rewriting across AE planning, WC delegation and claim handoff, and PA
background planning. It does not yet create accounting evidence, an approval
case, a VoucherCandidate, or a posted journal.

## Exact Context Propagation

The active path now preserves one canonical context and hash through:

1. `WorkIntent v1.2`;
2. generated `AgentPlan` delegation metadata;
3. compiled delegation schema `1.2`;
4. WC `DelegationSpec v1.2` and durable `wc_work_item` JSON;
5. claimed-work planning source v2; and
6. PA background `WorkIntent v1.2`.

The planning source also carries the original accountable requester,
delegation ID and revision, parent AgentExecution ID, Project authority,
completion policy, and result contract. The handoff event requester is the
accountable owner rather than the claiming worker. The installed routing
policy admits the product Project Agent profile for
`FINANCE.VOUCHER.APPROVE_AND_POST`.

Model-generated plan candidates cannot replace the context. The active
planner copies it from the admitted WorkIntent only after validating the
schema and semantic hash. Legacy non-M1 schema v1 paths remain valid and are
not silently upgraded.

## Replay and Failure Boundaries

Same-key, same-context replay returns the existing WorkItem. Changed context,
requester drift, malformed delegation lineage, stale or unsupported source
profiles, missing Project authority, and context/hash tampering fail closed.
M1 claimed work requires planning source v2; legacy planning source v1 is
retained only for non-M1 compatibility.

The shared `nex_runtime.business_context` validator is the single exact
validator used by AE and WC. The AE compatibility facade keeps its established
error contract while delegating canonical validation to the shared module.

## Persistence Reconciliation

No new table was introduced. Actual PostgreSQL testing identified that the
existing `ae_work_intent` constraints admitted only schema v1.1 and excluded
`BUSINESS_TRANSACTION`. Migration `2516_ae_m1_work_intent` updates those two
constraints to admit the already-approved v1.2 business record while
preserving JSON identity checks. The migration inventory manifest is updated
from the repository source inventory rather than a hard-coded count.

The protected AE/WC PostgreSQL test verifies WC JSON persistence, changed
context replay conflict, route and claim handoff, AE planning-source and
WorkIntent persistence, session restart reads, and zero-residue cleanup.

## Verification

- Focused context propagation and rejection tests: `35 passed`
- Focused affected regression: `194 passed`, `1` protected skip
- Actual AE/WC PostgreSQL smoke: `1 passed`, not skipped
- WC Slice Gate: `641 passed`, `22 skipped`; statement `98.32%`, branch
  `96.23%`
- AE Slice Gate: `6/6` commands passed
- AE regression: `6345 passed`, `47 skipped`
- Aggregate AE coverage:
  - statement `96.47%`
  - branch `94.74%`
- Active-product coverage:
  - statement `97.14%`
  - branch `95.06%`
- Contract validation:
  `269 schemas`, `319 examples`, `260 negative examples`, `10 OpenAPI`
- Repository Checkpoint Gate: `5/5` commands passed
- Checkpoint regression: `22321 passed`, `179 skipped`
- Checkpoint coverage: statement `98.37%`, branch `96.89%`
- Ruff and `git diff --check`: pass

The first Checkpoint run correctly detected the new migration-head inventory
drift. The source manifest was reconciled to migration `2516`; the final
Checkpoint passed. Ordinary Slice Gate protected skips remain opt-in suites;
the Slice-specific PostgreSQL test was run separately against the actual AE
and WC test databases.

## Closure Decision

`CP-M1-E2E-FX-01B.3` is closed. The M1 request context now reaches the claimed
Project Agent planning boundary durably and exactly, with replay and lineage
guards and without new product tables. `CP-M1-E2E-FX-01B.4` may now create the
authoritative proposal, approval, document, and VoucherCandidate preparation
flow from this preserved context.
