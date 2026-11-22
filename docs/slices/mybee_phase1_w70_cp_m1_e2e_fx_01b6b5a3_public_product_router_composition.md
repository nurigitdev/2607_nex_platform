# CP-M1-E2E-FX-01B.6B.5A.3 Public Product Router And Installed Composition

## Status

- Date: `2026-11-18`
- Status: `CLOSED`
- Parent amendment:
  `NeX_MyBee_CP_M1_E2E_FX_01B_6B_5A_Installed_Product_Coordinator_Authority_and_Dispatch_Closure_v1.0.md`
- Database migration: none
- Remote provider: not required
- Next Slice: `CP-M1-E2E-FX-01B.6B.5A.4`

## Public Routing Decision

The public claimed-work admission path now evaluates immutable Product
Capability Registry registrations before provider PLAN generation. Routing is
selected only by the WorkIntent capability hints and the exact capability
versions in the persisted snapshot. It does not inspect tenant, Project count,
amount, ratio, source kind, scenario name, or fixture values.

When one active Product coordinator matches, AE:

1. preserves the admitted INTENT and CONTEXT provider evidence;
2. starts the coordinator through its exact immutable registration;
3. persists the existing Product preparation checkpoint and generalized wait;
4. returns `PRODUCT_COORDINATION_STARTED`; and
5. does not treat provider PLAN output as business authority.

No match preserves the existing provider planning and deterministic compile
path. Multiple matches, registration drift, malformed lineage, or an inactive
coordinator fail closed.

## Installed Composition

`build_installed_product_planning_composition()` is the single generic factory
used by API and worker composition. It installs:

- the immutable coordinator runtime registry;
- the public Product router;
- the generic `PRODUCT_COORDINATOR` assignment handler when an active exact
  runtime exists; and
- the protected Product authority-event admission boundary when an active
  exact runtime exists.

The handler rehydrates WorkIntent, AgentContext, capability snapshot,
AgentExecution, checkpoint, wait, event, and resume route through existing
repositories. READY activation reuses the existing AgentPlan, PlanValidation,
ExecutablePlan, AgentExecution, RuntimeJob, and MultiStepEngine stores and
scheduler. No second queue, worker, plan store, or Product-specific dispatcher
was introduced.

The internal event route is `POST /internal/v1/product-planning-events`. It
admits only signed `nex-eos` service callers and maps typed coordinator and
resume failures to bounded fail-closed responses.

## Activation Boundary

The installed M1 registration remains `CONTRACT_ONLY` in this Slice. API and
worker processes share the same contract composition, but the worker handler
and event admission are absent until `.5A.4` supplies an active immutable
runtime lock. Product resume jobs therefore remain queued rather than being
claimed by an incomplete process.

The source-backed storage-fit audit was reconciled to prove both the
`CONTRACT_ONLY` builder default and its explicit propagation into the
registration. The MyBee installed configuration test now uses the canonical
M1 capability registry instead of the retired Golden A single-capability
registry.

## Compatibility And Ownership

Ordinary non-Product semantic planning, executable-step dispatch,
WorkResult/NSL resume behavior, lease/retry handling, and background result
closure are unchanged. Existing Product coordinator errors retain their typed
code, detail, and retryability at the new public boundary; unexpected defects
are not swallowed.

The AE source inventory is now `192` modules: `182` active product, `5`
compatibility, and `5` historical. The source-backed active import graph grew
from `97` to `103` modules because the public composition now reaches the
coordinator and activation chain. Historical quarantine and deployment
conflicts remain zero.

## Verification

- focused new Product router/event boundary: `16 passed`
  - `product_planning_runtime.py`: statement/branch `100% / 100%`
  - `product_planning_event_api.py`: statement/branch `100% / 100%`
- focused semantic admission, claim handoff, resume, activation, composition,
  and process regression: `245 passed`
- protected runtime and ownership regression after canonical registry
  reconciliation: `56 passed`
- AE Slice Gate: `6696 passed`, `51 skipped`
  - statement coverage: `96.37%`
  - branch coverage: `94.60%`
  - commands: `6/6`
- active product coverage: statement `97.00%`, branch `94.90%`
- contract validation: `274` schemas, `320` examples, `260` negative examples,
  `10` OpenAPI documents
- Golden Journey transition and demo/product dependency audits: PASS
- AE coverage ownership: PASS, no active/historical conflict
- lint, formatting, compile, and diff checks: PASS
- evidence:
  - `reports/quality/mybee-w70-cp-m1-01b6b5a3-ae-slice-gate.json`
  - `reports/coverage/mybee-w70-cp-m1-01b6b5a3-ae-slice-gate.report_ae_coverage_ownership.json`

Actual AE/EOS/OA/WC PostgreSQL protected acceptance remains assigned to
`.5A.5`. This Slice does not require generation, embedding, or reranking
providers.

## Closure

`CP-M1-E2E-FX-01B.6B.5A.3` is closed. AE now has one public, capability-driven
Product routing and installed composition boundary without scenario-specific
business selection, fixture authority, duplicate runtime machinery, or a new
database schema. `.5A.4` may activate an exact Product coordinator runtime and
freeze the rollback lock through this same composition.
