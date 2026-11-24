# W80-CA00F.1: Sequential Approval Activation and Visibility Hardening

## Outcome

- Preserved the existing EOS multi-stage approval engine. Policy stages may be
  known in advance, but only the current stage is published to WC.
- Added explicit regression evidence that the business stage is the only
  published gate at submission and that the accounting stage appears only
  after business approval.
- Added rejection coverage proving that a business rejection leaves no active
  accounting stage, publishes no second WorkItem, and creates no accounting
  approval evidence.
- Changed the AE Web formal-approval stepper labels to distinguish `완료`,
  `현재 결재`, and `대기`. A future stage is visible only as non-actionable route
  context.

## Persistence and Contracts

- Database migration: none.
- Public backend API change: none.
- Approval policy, case, evidence, WC WorkItem, and decision contracts remain
  unchanged.
- The current `ACTIVE/WAITING` and `active_stage_order` mechanics remain the
  authority boundary.

## Verification

- Focused EOS sequential approval regression: `2 passed`.
- Focused AE Web approval surface regression: `12 passed`.
- EOS Slice Gate: `2,316 passed`, `67 skipped`; statement `96.80%`, branch
  `94.82%`.
- AE Web Slice Gate: `297 passed`; statement `97.78%`, branch `97.28%`;
  contract validation and dependency audits passed.
- The protected PostgreSQL cases remain explicitly disabled in the ordinary
  Slice Gate. This Slice changes no database contract and requires no migration.
