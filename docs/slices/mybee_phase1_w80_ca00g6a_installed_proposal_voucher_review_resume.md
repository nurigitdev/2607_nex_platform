# W80-CA00G.6A Installed Proposal/Voucher User-Review Wait and Resume Composition Closure

## Status

IMPLEMENTED / PROTECTED POSTGRESQL ACCEPTED / AE SLICE GATE PASSED

## Product Boundary

The installed MyBee transaction runtime now preserves the two requester review
boundaries that the earlier compressed composition skipped. EOS remains the
authoritative owner of BusinessProposal, VoucherCandidate, business approval,
and accounting approval state. AE stores only the existing Product preparation
checkpoint, generalized wait/event, and RuntimeJob resume lineage.

No scenario-specific queue or persistence aggregate was added. Migration
`2518_ae_product_requester_review_resume.sql` extends the admitted values and
shape checks on the existing Product preparation wait/event structures. It
does not create a table or queue.

## Installed State Machine

The installed runtime enables the review-aware transaction preparation profile:

1. AI output is admitted as an EOS `BusinessProposal` in `DRAFT` state.
2. AE records `WAITING_PROPOSAL_REVIEW` and stops until the authenticated owner
   edits the proposal, selects an approval line, and explicitly submits it.
3. The existing generalized event admission resumes the Product RuntimeJob as
   `WAITING_BUSINESS_APPROVAL` without bypassing EOS/WC approval authority.
4. Final business approval is resolved from the authoritative EOS receipt and
   materialized as an EOS `VoucherCandidate` in `DRAFT` state.
5. AE records `WAITING_VOUCHER_REVIEW` and stops until the same owner reviews,
   revises, validates, and explicitly submits the voucher.
6. The admitted voucher event resumes the job as
   `WAITING_ACCOUNTING_APPROVAL`; only final accounting approval can advance it
   to `READY_FOR_D04`.

The legacy compressed preparation path remains available for historical replay
compatibility, but installed canonical composition selects the review-aware
profile.

## Admission and Safety

- Review events are domain separated and bind tenant, requester, review kind,
  authoritative reference, and receipt identity.
- An unrelated manually created proposal or voucher does not satisfy a Product
  wait merely because its identifier is syntactically valid.
- Cross-owner, cross-tenant, wrong-kind, stale-reference, and malformed receipt
  admission fails closed.
- Exact replay returns the same admitted event and RuntimeJob resume identity;
  semantic drift is rejected.
- EOS write success followed by AE acknowledgement loss is recoverable by
  replaying the same explicit submit operation.
- Restart uses the persisted wait/event and Product preparation checkpoint;
  no in-memory-only continuation is required.
- Existing EOS/OA separation-of-duties checks remain authoritative. The new
  composition introduces no requester self-approval path.

## Installed Admission

- Transaction preparation adapter: `1.1.0`, with eight operations covering the
  four review/approval boundaries.
- Product coordinator activation: registry version `4`, adapter `1.2.0`.
- Canonical activation and rollback locks: version `5`.
- Compose, OCI build contexts, and packaged AE runtime select the version `5`
  locks while preserving versions `1` through `4` as historical artifacts.

## Verification

- Focused proposal/voucher, orchestration, persistence, replay, owner, tenant,
  malformed-input, and acknowledgement-loss tests: `111 passed`.
- Broad W70/W80 AE regression: `759 passed`, `8 skipped`.
- Actual isolated-schema `nex_ae_test` migration/state smoke for all four waits,
  restart, replay, and acknowledgement loss: `1 passed`.
- Actual isolated-schema `nex_eos_test` proposal smoke: `21 passed`.
- Actual isolated-schema `nex_eos_test` VoucherCandidate smoke: `1 passed`.
- AE Slice Gate: `PASS`; statement `96.42%`, branch `94.61%`; all `6/6`
  commands completed in `782.016s`.
- Contract validation passed for `280` schemas, `322` examples, `260` negative
  examples, and `10` OpenAPI documents. Golden Journey transition,
  demo-to-product dependency, and AE coverage ownership audits passed.
- Ruff, compileall, and repository diff checks passed.

No remote model provider is required for this corrective Slice. The next parent
step is `W80-CA00G.7: Protected Live Matrix, Repository Full Gate, and As-Built
Closure`.
