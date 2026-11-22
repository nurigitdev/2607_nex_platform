# CP-M1-E2E-FX-01B.6B.5A.3A.1 Product Planning Proposal Contract And Policy

## Status

- Date: `2026-11-18`
- Status: `CLOSED`
- Parent amendment:
  `NeX_MyBee_CP_M1_E2E_FX_01B_6B_5A_3A_Advisory_Product_Planning_Proposal_and_Deterministic_Execution_Boundary_v1.0.md`
- Database migration: none
- Remote provider: not required
- Next Slice: `CP-M1-E2E-FX-01B.6B.5A.3A.2`

## Planning Policy

Every Product coordinator registration now carries an immutable planning
policy. The admitted modes are:

- `DETERMINISTIC_ONLY`
- `PROVIDER_ASSISTED_OPTIONAL`
- `PROVIDER_ASSISTED_REQUIRED`

The policy binds the proposal schema, prompt binding, admission policy,
deterministic fallback, and authorized proposal consumers into the
registration hash. Optional mode requires an explicit fallback; deterministic
and required modes reject one. Provider-assisted modes must also declare at
least one consumer.

The M1 registration uses `PROVIDER_ASSISTED_REQUIRED` with the existing
Project-delegation prompt binding and strict proposal admission. This is an
immutable capability policy, not tenant-, scenario-, Project-count-, ratio-,
or fixture-specific selection.

## Provider-Neutral Proposal

`ProductPlanningProposal` is a provider-neutral, hash-bound advisory artifact.
It preserves:

- WorkIntent, AgentContext, execution, and coordinator lineage;
- exact immutable Product registration and planning-policy projections;
- admitted PLAN evidence and semantic candidate storage reference;
- candidate semantic hash and provider provenance; and
- only capabilities already admitted by the capability snapshot.

The proposal explicitly declares `provider_plan_authoritative=false` and does
not contain an AgentPlan, ExecutablePlan, approval proof, business evidence,
or provider-generated business identifier. Candidate content remains in the
existing private semantic-candidate store; the proposal carries only its
opaque reference and hashes.

Validation fails closed for schema, policy, evidence, candidate hash,
execution lineage, WorkIntent/context lineage, capability, or semantic-hash
drift. The proposal therefore cannot become execution authority by itself.

## Compatibility

No queue, worker, plan store, checkpoint table, or migration was added.
Non-Product planning remains unchanged. Product deterministic materialization
and preparation remain the only sources of authoritative AgentPlan and
ExecutablePlan state; provider wiring is deferred to `.5A.3A.2`.

## Verification

- focused policy/proposal tests: `27 passed`
  - `product_planning_coordinators.py`: statement/branch `100% / 100%`
  - `product_planning_proposals.py`: statement/branch `100% / 100%`
- Product and ownership regression: `134 passed`
- AE Slice Gate: `6714 passed`, `51 skipped`
  - statement coverage: `96.38%`
  - branch coverage: `94.63%`
  - commands: `6/6`
- active product coverage: statement `97.01%`, branch `94.93%`
- contract validation: `274` schemas, `320` examples, `260` negative examples,
  `10` OpenAPI documents
- Golden Journey transition, demo/product dependency, and AE ownership audits:
  PASS
- lint, formatting, and diff checks: PASS
- evidence:
  - `reports/quality/mybee-w70-cp-m1-01b6b5a3a1-ae-slice-gate.json`
  - `reports/coverage/mybee-w70-cp-m1-01b6b5a3a1-ae-slice-gate.report_ae_coverage_ownership.json`

## Closure

`CP-M1-E2E-FX-01B.6B.5A.3A.1` is closed. Product planning now has an
immutable policy and a provider-neutral advisory proposal contract while
retaining deterministic execution authority and all existing runtime stores.
