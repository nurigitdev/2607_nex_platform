# CP-M1-E2E-FX-01B.6B.5A.3A.2 Provider Proposal Admission And Router Wiring

## Status

- Date: `2026-11-18`
- Status: `CLOSED`
- Parent amendment:
  `NeX_MyBee_CP_M1_E2E_FX_01B_6B_5A_3A_Advisory_Product_Planning_Proposal_and_Deterministic_Execution_Boundary_v1.0.md`
- Database migration: none
- Remote provider: not required
- Next Slice: `CP-M1-E2E-FX-01B.6B.5A.3A.3`

## Provider Proposal Admission

The claimed Product route now resolves its exact immutable coordinator
registration before PLAN candidate generation. `DETERMINISTIC_ONLY` skips the
provider PLAN stage. Provider-assisted modes generate and admit a PLAN
candidate as a non-authoritative `ProductPlanningProposal` whose suggested
capabilities are limited to the exact Product registration.

Product proposal policy and model-revision semantic calibration remain
separate contracts. The Product policy binds the prompt and authorized
consumer boundary; the admitted evidence preserves its provider/model-specific
calibration policy as provenance.

The provider path does not bind or persist an `AgentPlan`. The existing
deterministic Product preparation and materialization path remains the only
execution-authority source.

## Durable Boundary

The full provider proposal remains outside the durable Product checkpoint.
The existing `authority_refs` JSON stores only a bounded, validated reference:

- proposal semantic hash;
- candidate ID and semantic hash; and
- opaque private candidate payload storage reference.

Provider response content and provider provenance are not copied into the
checkpoint. Required-policy replay rejects a different proposal before any
preparation mutation. Approval resumes carry the same bounded reference to
`READY_FOR_D04`.

The deterministic materializer accepts that reference only as lineage. Its
D12/D04 operations and authoritative inputs still come from Product authority
data, while `planner_provenance.route_decision_ref` is bound to the proposal
hash.

## Compatibility And Ownership

- Non-Product planning and deterministic-only Product registrations retain
  their previous behavior.
- No queue, worker, checkpoint table, plan table, API field, or migration was
  added.
- `product_planning_proposals.py` is now intentionally reachable from the
  canonical installed Product import graph. The ownership baseline records
  this named promotion on top of the previous active-import baseline instead
  of replacing it with an unexplained count.
- Prompt provenance now records the actual selected prompt binding rather than
  a hard-coded default binding.

## Verification

- focused Product proposal/router/preparation/activation regression:
  `146 passed`
- AE Slice Gate: `6718 passed`, `51 skipped`
  - statement coverage: `96.31%`
  - branch coverage: `94.52%`
  - commands: `6/6`
- active product coverage: statement `96.94%`, branch `94.82%`
- contract validation: `274` schemas, `320` examples, `260` negative examples,
  `10` OpenAPI documents
- Golden Journey transition, demo/product dependency, and AE ownership audits:
  PASS
- lint, formatting, and diff checks: PASS
- evidence:
  - `reports/quality/mybee-w70-cp-m1-01b6b5a3a2-ae-slice-gate.json`
  - `reports/coverage/mybee-w70-cp-m1-01b6b5a3a2-ae-slice-gate.report_ae_coverage_ownership.json`

## Closure

`CP-M1-E2E-FX-01B.6B.5A.3A.2` is closed. The provider can now propose a
Product plan through the admitted semantic-candidate path, but execution
authority, durable preparation, plan materialization, and scheduling remain
deterministic and product-owned.
