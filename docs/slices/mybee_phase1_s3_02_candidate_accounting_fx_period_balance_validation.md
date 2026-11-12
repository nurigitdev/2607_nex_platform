# MyBee Phase 1 S3-02 Candidate Accounting/FX/Period/Balance Validation

## Status

- Slice: `S3-02`
- Status: implemented and verified
- EOS migration: none; validation is read-only
- Remote model providers: not required
- Date: `2026-11-12`

## Boundary Decision

S3-02 validates the immutable S3-01 `VoucherCandidate` revision without
changing candidate state, appending a revision, or posting to the general
ledger. The validation boundary is owned by NeX-EOS because EOS is the source
of record for legal entity, period, account policy, FX evidence, and voucher
accounting semantics.

```text
current immutable candidate revision/hash
  -> ACTIVE legal entity and functional currency
  -> exact OPEN accounting period
  -> effective approved COA, PostingRule, and company account policy
  -> approved FX snapshot or exact same-currency rate
  -> original and functional debit/credit balance
  -> hash-bound validation receipt
```

The accounting rules initially lived under `domains/mybee`, but the W30
Checkpoint exposed that EOS installed runtimes and OCI images intentionally do
not package that policy-consumer package. The rules were therefore moved to
`nex_eos.accounting_rules`. This preserves the existing deployment boundary and
keeps executable accounting validation with its authoritative service.

## Validation Rules

The service fails closed unless all of the following are true:

1. the requested revision is current and its candidate hash matches exactly;
2. the legal entity is active at the explicit timezone-aware `as_of` instant;
3. one exact accounting period contains the accounting date and is `OPEN`;
4. the account catalog and PostingRule releases are published and effective;
5. every account is approved, postable, a leaf, effective, and admits the
   transaction currency through the company account policy;
6. foreign-currency candidates resolve an approved `TRANSACTION_SPOT`
   `RateSnapshot`; same-currency candidates use an exact rate of `1` without an
   FX repository lookup;
7. each line has exactly one positive debit or credit and contiguous numbering;
8. original-currency and line-level functionalized debit/credit totals balance.

Amounts use `Decimal` and `ROUND_HALF_EVEN`. Functionalization is applied once
per line using an admitted currency minor-unit policy. Unknown currency scales,
non-finite amounts, invalid rates, stale evidence, missing policies, and balance
errors produce typed errors rather than fallback values.

## API And Evidence

- Operation: `FINANCE.VOUCHER_CANDIDATE.VALIDATE`
- Endpoint:
  `POST /internal/v2/finance/voucher-candidates/{candidate_id}/validation`
- Admission: service token only
- Mutation: none

The response binds the candidate identity, revision, candidate hash, legal
entity, Project UUID/code, ApprovedDocument identity, period, account-policy
set hash, PostingRule hash, FX evidence set hash, accounting-rule profile hash,
functionalized lines/totals, and validation instant into a deterministic
validation hash. S3-03 may consume and revalidate this receipt when advancing
candidate state; S3-02 itself does not persist or freeze it.

OpenAPI, request/result JSON Schemas, positive examples, and a negative
missing-hash fixture were added. Existing VoucherDraft v1 and VoucherCandidate
v2 create/read contracts remain unchanged.

## PostgreSQL Protected Smoke

Actual `nex_eos_test` execution passed:

```text
tests: 1 passed, 25 deselected
database: postgresql://nex_eos_user@127.0.0.1:5432/nex_eos_test
```

The smoke applied EOS migrations through 2534 in an isolated schema, inserted
actual legal entity, period, COA, PostingRule, company policy, FX snapshot, and
candidate rows, validated JPY/KRW quote-unit normalization to `9.605`, rejected
a `CLOSING` period, dropped the schema, and verified zero residue.

## Slice Gate

```text
status: PASS
commands: 6/6
tests: 1,423 passed, 44 skipped
statement coverage: 96.45% (threshold 96.00%)
branch coverage: 94.49% (threshold 94.00%)
accounting_rules.py: statement/branch 100.00%/100.00%
candidate_validation.py focused coverage: statement/branch 100.00%/100.00%
contract validation: PASS (237 schemas, 295 examples, 247 negative, 10 OpenAPI)
Golden Journey transition audit: PASS
demo-to-product dependency audit: PASS
```

Machine-readable evidence:

- `reports/quality/mybee_w30_s3_02_slice_gate.json`

## W30 Checkpoint Gate

The first Checkpoint run exposed stale EOS OpenAPI/migration baseline values
and the installed-runtime import boundary described above. Historical CA01
documents remain unchanged. The active compatibility lock and source manifest
were reconciled to the current EOS OpenAPI and migration 2534, while the W30
test now records that 2530 was consumed as reserved and 2531-2533 moved S3-01
to 2534.

After those source-backed corrections, the full Checkpoint passed:

```text
status: PASS
commands: 6/6
tests: 20,696 passed, 155 skipped
statement coverage: 98.57% (threshold 95.00%)
branch coverage: 97.16% (threshold 94.00%)
accounting_rules.py: statement/branch 100.00%/100.00%
contract validation: PASS
Golden Journey transition audit: PASS
demo-to-product dependency audit: PASS
duration: 1,408.969 seconds
```

Machine-readable evidence:

- `reports/quality/mybee_w30_s3_02_checkpoint_gate.json`

## Next Entry

S3-03 may add candidate review/state transition and durable validation evidence.
It must revalidate authoritative period, account-policy, FX, Project, document,
and candidate revision/hash state at the transition boundary rather than
treating this read-only S3-02 receipt as permanent authorization.
