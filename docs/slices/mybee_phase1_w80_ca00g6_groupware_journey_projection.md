# W80-CA00G.6 Groupware Journey Integration and Result Projection

## Status

IMPLEMENTED / PROTECTED POSTGRESQL ACCEPTED / SLICE GATES PASSED

## Product Boundary

EOS remains authoritative for BusinessProposal, VoucherCandidate, approval, and
PostedJournal state. This Slice adds a read-only user-facing journey projection;
it does not add another workflow engine, state table, or approval status.

The projection deliberately does not infer authority state that EOS has not
persisted. A submitted proposal is shown as business approval in progress. A
`READY_FOR_REVIEW` VoucherCandidate is shown as accounting approval in progress
until an existing product transition moves it to correction or posting.

## Contract

- `eos_business_journey.v1` exposes ordered, user-facing steps without internal
  UUID, principal, policy, evidence, or authority payload.
- BusinessProposal maps to `품의서 작성 → 품의 결재 → 전표 작성`.
- VoucherCandidate maps to `전표 검토 → 회계 결재 → 총계정원장 반영`.
- Every step has an explicit status: `COMPLETED`, `CURRENT`, `AVAILABLE`,
  `UPCOMING`, `RETURNED`, `REJECTED`, `CANCELLED`, or `BLOCKED`.
- Unsupported source states fail closed instead of being projected as a
  misleading success state.
- AE continues to pass EOS projections through its owner-scoped session facade.
  The browser performs strict ordering and status admission before rendering.
- AE Web uses one shared compact journey component on both the proposal and
  voucher review surfaces. The current step is exposed with `aria-current`.

## Persistence

No migration was added. Proposal, scoped-approval, candidate-review, and
journal-posting source-of-truth records remain unchanged.

## Verification

- EOS journey projector: `12 passed`; statement and branch coverage
  `100% / 100%`.
- Focused EOS integration: `21 passed`.
- AE Web focused tests: `14 passed`; full React Gate: `35 files`, `155 passed`.
- TypeScript typecheck and production build passed. Existing dependency
  directive and bundle-size warnings remain non-blocking and unchanged.
- Actual `nex_eos_test` proposal and voucher projection smoke: `2 passed`; test
  database identity was verified and isolated schemas left zero residue.
- EOS Slice Gate: `2431 passed`, `69 skipped`; statement `96.37%`, branch
  `94.19%`, both above the preceding Slice baseline.
- Contract validation passed for `280` schemas, `322` examples, `260` negative
  examples, and `10` OpenAPI documents. Golden Journey transition and
  demo-to-product dependency audits passed.

No remote model provider is required for this Slice.
