# W80-CA00G.1 Proposal Persistence and Revision Contract Closure

## Status

IMPLEMENTED / PROTECTED POSTGRESQL ACCEPTED

## Source-Backed Decision

The pre-implementation audit found no existing editable business-proposal SoR.
`eos_approved_document_envelope` is an immutable final approval artifact and
`eos_voucher_candidate` begins the later accounting-review lifecycle. Neither
is reused as a proposal draft store.

EOS now owns an additive `eos_business_proposal` aggregate and append-only
`eos_business_proposal_revision` history. AE remains a protected facade and
projection owner only.

## Contract

- Aggregate states are `DRAFT`, `SUBMITTED`, `APPROVED`, `REJECTED`, and
  `WITHDRAWN`.
- The aggregate stores identity, state, current revision, optimistic version,
  and later approval/envelope bindings only.
- Each revision stores proposal text, amount/currency, validity, Project scope,
  attachment metadata, and three semantic hashes.
- Persisted revisions are immutable and physical proposal deletion is rejected
  by PostgreSQL triggers.
- Revision requires both `expected_version` and `expected_revision`.
- Company and requester identity cannot change under one proposal identity.
- Editing a rejected proposal appends a revision, returns it to `DRAFT`, and
  clears stale submission and approval bindings.
- Attachment bytes remain in private object storage; only object reference,
  size, media type, and content hash enter EOS.
- All datetime wire values are normalized to UTC, independent of database
  session timezone.

## Migration

`2549_eos_business_proposal_draft.sql` is admitted after the W60 privacy
migration in the append-only NeX-EOS inventory. Tests verify inventory
membership and ordering instead of freezing the repository-wide head forever.
Table and constraint names remain within PostgreSQL identifier limits.

## Verification

- Focused persistence tests: `20 passed`, one protected test skipped by default.
- New module branch-aware coverage: `93%`.
- Related Project application, approval policy, approved-document, and
  VoucherCandidate regression: `212 passed`, protected tests skipped by
  explicit profile only.
- Actual `nex_eos_test` protected smoke: migration applied in an isolated
  schema; LegalEntity seed, create, exact replay, revision append, and schema
  zero-residue passed.
- Ruff check and format passed.
- NeX-EOS Slice Gate: `2339 passed`, `68 skipped`; statement `96.74%`, branch
  `94.71%`; contract, transition, dependency, and tiered gate checks passed.

No remote model provider is required for this Slice.
