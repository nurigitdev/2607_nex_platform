# W80-CA00H.1 Approval-Line Priority and Rejection-Reason Contract Closure

## Status

IMPLEMENTED / SLICE GATES PASSED

## Product Boundary

- The proposal approval line now appears immediately after the proposal journey
  and before editable business fields.
- Editing any proposal policy input invalidates the current preview, selected
  approvers, and submission confirmation.
- WC rejects a `BUSINESS_FORMAL` rejection without a non-empty reason before
  any decision or outbox mutation.
- The admitted reason is trimmed and retained in the existing immutable WC
  decision record.
- EOS derives the requester-visible rejection reason from the existing scoped
  approval decision linked by tenant and approval case. No new table or
  migration was introduced.
- AE Web displays the bounded reason on a rejected proposal; service and
  storage identifiers remain hidden.

## Implementation

- Hardened `ApprovalDecisionService.decide()` for `BUSINESS_FORMAL` rejection.
- Extended the EOS proposal projection with nullable `rejection_reason`.
- Extended the AE Web proposal client contract and proposal workspace.
- Moved approval controls above the body and added explicit stale-preview
  invalidation behavior.
- Added focused zero-residue, immutable projection, ordering, invalidation, and
  requester-display tests.

## Verification

- Focused Python regression: `55 passed`, `1 protected test skipped`.
- Focused React regression: `6 passed`.
- AE Web TypeScript check: passed.
- NeX-WC Slice Gate: `760 passed`, `27 skipped`; statement `97.37%`, branch
  `94.64%`.
- NeX-EOS Slice Gate: `2440 passed`, `69 skipped`; statement `96.37%`, branch
  `94.19%`.
- NeX-AE-Web Slice Gate: `297 passed`; statement `97.78%`, branch `97.28%`.
- Contract validation, transition audit, and demo/product dependency audit:
  passed for all three gates.

Actual cross-service PostgreSQL and authenticated Playwright evidence remain
owned by `W80-CA00H.5`. No remote model provider is required for this Slice.
