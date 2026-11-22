# MyBee Phase 1 S2-04 Approved Document Consumption Guard

## Status

- Slice: `S2-04`
- Status: implemented and verified
- Dependencies: `S2-01`, `S2-02`
- Requirements: `SRS-DOC-003`, `SRS-DOC-004`, `SRS-DOC-005`
- Gates: `G-DOC`, `PG-CONCURRENCY`

## Boundary

S2-04 adds the EOS allowance-consumption guard for an approved document. It
does not expose a standalone consumption write API. The adapter can run only
with the active SQLAlchemy session of an existing pending EOS business
operation, so a future S4 journal commit and its allowance consumption can
share one transaction and rollback boundary.

VoucherCandidate and PostedJournal remain S3/S4 authoritative aggregates.
This Slice accepts their immutable UUID references without creating
provisional copies of those future models.

## Persistence

Migration `2529_eos_approved_document_consumption.sql` adds the immutable
`eos_approved_document_consumption` ledger. It records:

- tenant, company, envelope and consumption identities;
- source document line plus optional supplier invoice or payroll-period refs;
- normalized source-identity hash;
- candidate revision, posted journal and business operation lineage;
- original-currency consumed amount, commit state and posting time;
- immutable consumption semantic hash and optional reversal journal ref.

Candidate revision is unique per tenant/company. Source identity is unique per
tenant/company/envelope. The source hash normalizes nullable invoice and
payroll refs, avoiding PostgreSQL nullable-unique ambiguity. PostgreSQL
triggers reject update and delete; reversal never silently restores allowance.

## Admission And Concurrency

`EosApprovedDocumentConsumptionAdapter.consume_in_session()` performs the
following fail-closed sequence:

1. validate stable identities, money precision and ISO currency;
2. lock the exact approved-document envelope with `SELECT ... FOR UPDATE`;
3. require the matching EOS business operation to be `PENDING`;
4. require an active, in-window envelope for the same company;
5. require exact original-currency equality;
6. admit exact replay, but reject candidate or source semantic drift;
7. sum committed consumption under the envelope lock;
8. reject a write that exceeds the approved amount;
9. insert the immutable consumption in the caller's transaction.

The approved-document GET projection now computes `remaining_amount` from
committed consumption rather than echoing the original approved amount. Its
public field set is unchanged.

## Verification

- Focused S2-01/S2-04 coverage: `65 passed`, `2 skipped`; aggregate statement
  and branch coverage `99%`.
  - new consumption adapter: statement/branch `99%`;
  - approved-document repository: statement/branch `99%`.
- Actual `nex_eos_test` protected smoke: `31 passed`.
  - connected as `nex_eos_user` to `nex_eos_test`;
  - applied every EOS migration through `2529` in an isolated schema;
  - concurrently submitted two `60.0000 KRW` consumptions against a
    `100.0000 KRW` allowance;
  - committed exactly one request and rejected the other with
    `EOS_APPROVED_DOCUMENT_ALLOWANCE_EXCEEDED`;
  - verified remaining allowance `40.0000` and immutable update/delete guards;
  - dropped the isolated schema after the test (zero residue).
- NeX-EOS Slice Gate: `1198 passed`, `39 skipped`; statement coverage
  `97.11%`, branch coverage `96.36%`.
- Contract validation: `233` schemas, `292` examples, `245` negative examples
  and `10` OpenAPI documents passed.
- Golden Journey transition and product dependency audits: passed.
- Machine-readable evidence:
  - `reports/quality/mybee-s2-04-nex-eos.coverage.json`
  - `reports/quality/slice-nex-eos.coverage.json`

## Deferred

- S3 authoritative VoucherCandidate revision lookup and stale-candidate guard
- S4 PostedJournal commit composition using this transaction-bound adapter
- tolerance-policy evaluation beyond exact approved amount
- explicit FX conversion or amendment policy for a different billing currency
- reversal/credit-note accounting workflow and separate restoration decision
