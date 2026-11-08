# P8-S32 Approval Transition Contract Pack

## Scope

Freeze the additive P8.3 machine-readable contracts for human approval without
modifying the Frozen v2.1 approval files or extending the delegated WorkItem
aggregate.

## Decisions

- WC ApprovalWorkItem is a separate aggregate from delegated `wc_work_item`.
- The approval aggregate does not carry delegation, routing, Claim, Assignment,
  or lease fields.
- Runtime infrastructure such as semantic hashing, OA authorization, outbox
  delivery, JobQueue, transaction management, and operational events remains
  reusable.
- Canonical approval domains are `AGENT_FORMAL`, `NSL_WRITE`, and the additive
  `BUSINESS_FORMAL` domain.
- `BUSINESS_FORMAL` remains an EOS-backed domain and cannot substitute for
  `NSL_WRITE` or `AGENT_FORMAL`.
- `HumanGateView` preserves the exact approval domain and contains only a safe
  presentation projection.
- ApprovalDecision requires current OA evidence metadata and rejects raw token
  fields.
- Approval event type and approval domain must match exactly.
- Real NSL wait/resume and AE Platform ApprovalEvidence remain P8.4 scope.

## Contract Inventory

- `WC ApprovalWorkItem Transition v1`
- `WC ApprovalDecision Transition v1`
- `P8 HumanGateView Additive Transition v1`
- `WC Approval Decision Event v1`
- four positive examples and four fail-closed negative examples

## Persistence Direction

P8-S33 may introduce the concise WC-owned relations
`wc_approval_work_item`, `wc_approval_decision`, and `wc_approval_outbox`.
Existing `wc_work_item`, `wc_claim`, and `wc_assignment` remain unchanged.

## Verification

- focused P8-S32 and P8-S23 contract regression: `20 passed`
- broader WC/P7 regression: `333 passed`, `12 protected skips`
- canonical contract validation: PASS
  - schemas: `183`
  - examples: `245`
  - negative examples: `214`
  - OpenAPI documents: `9`
- whitespace validation: pass
