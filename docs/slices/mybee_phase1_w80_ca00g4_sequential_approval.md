# W80-CA00G.4 Sequential Approval, Rejection, and Envelope Finalization

## Status

IMPLEMENTED / PROTECTED POSTGRESQL ACCEPTED / SLICE GATE PASSED

## Product Boundary

The existing EOS `ScopedApprovalCase v2`, WC approval work item, OA fresh
authorization, and document-signoff finalizer remain the canonical approval
runtime. This Slice does not introduce another approval engine.

BusinessProposal adds only the product composition required to bind an admitted
proposal revision and its user-selected approval line to that runtime. There
are no tenant-specific thresholds, fixed approvers, fixed Project counts, or
scenario fixture values in product code.

## Contract

- Submission materializes one immutable nomination per policy stage. Every
  nomination binds stage order, required position, selected OA subject,
  authority hash, and one approval-line hash.
- The requester cannot nominate self. Missing stages, role drift, malformed
  nominations, and mixed approval-line hashes fail closed.
- Only stage 1 is active initially. An approval activates exactly the next
  policy stage and its selected principal; later stages remain inaccessible.
- Fresh OA role and nominated-principal checks are both required for every
  decision.
- Rejection is terminal and does not create an ApprovedDocumentEnvelope.
- Final approval creates the existing immutable ApprovedDocumentEnvelope and
  projects the exact terminal result to the BusinessProposal aggregate in the
  same EOS transaction.
- Rejected proposals remain correctable through a new immutable revision and a
  new approval submission.
- A crash between proposal submission persistence and approval-case binding is
  recoverable. Exact revision, preview hash, and selected-principal replay
  recreates or reuses the deterministic case; drift is rejected.

## Persistence

Migration `2551_eos_scoped_approval_nomination.sql`:

- adds `target_approver_ref` to `eos_scoped_approval_case`;
- adds the admitted approval line to `eos_business_proposal`;
- adds owner-scoped `eos_scoped_approval_nomination` records keyed by tenant,
  case, and stage order.

The nomination table stores authority lineage, not another business approval
aggregate. Existing scoped cases, work items, decisions, document envelopes,
and proposal revisions remain authoritative.

## Verification

- Focused sequential approval, signoff, product API, replay, malformed-input,
  policy-drift, and SoD tests: `82 passed`, `1 skipped` by protected profile.
- Actual `nex_eos_test` migration applied through heads `2549`, `2550`, and
  `2551`; database identity was `nex_eos_test` / `nex_eos_user`.
- PostgreSQL schema inspection confirmed
  `eos_scoped_approval_nomination`, `target_approver_ref`, and
  `approval_line` are present.
- EOS Slice Gate: `2392 passed`, `68 skipped`; statement `96.36%`, branch
  `94.14%`.
- Contract validation passed for `280` schemas, `322` examples, `260` negative
  examples, and `10` OpenAPI documents.
- Golden Journey transition audit and demo-to-product dependency audit passed.

No remote model provider is required for this Slice.
