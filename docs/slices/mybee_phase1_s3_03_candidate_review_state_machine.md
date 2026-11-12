# MyBee Phase 1 S3-03 Candidate Review State Machine

## Status

- Slice: `S3-03`
- Status: implemented and verified
- EOS migration: `2535_eos_candidate_review_state`
- Remote model providers: not required
- Date: `2026-11-12`

## Boundary Decision

S3-03 makes accounting review an explicit, durable state machine around the
current immutable `VoucherCandidate` revision. It does not turn a WC approval
decision into a ledger posting operation.

```text
DRAFT or RETURNED_FOR_CORRECTION
  -> SUBMIT + current authoritative S3-02 validation
  -> READY_FOR_REVIEW
  -> WC APPROVE: retain READY_FOR_REVIEW and approval evidence only
  -> WC REJECT(reason): RETURNED_FOR_CORRECTION
  -> explicit INVALIDATE(reason): RETURNED_FOR_CORRECTION
```

`APPROVE` cannot mutate the Candidate to `POSTED`; the later accounting-proof
admission and posting Slice owns that boundary. Exact retries return the prior
transition evidence. Changed replay semantics, stale versions, changed hashes,
or concurrent state changes fail closed.

## Persistence And Transaction Boundary

Migration 2535 extends the Candidate and accounting-review constraints without
changing VoucherDraft v1. `eos_candidate_review_event` stores immutable
`SUBMIT`, `RETURN`, and `INVALIDATE` evidence with:

- tenant, Candidate, revision/hash, and approval-case lineage;
- expected/resulting Candidate version for compare-and-swap;
- actor, reason, S3-02 validation hash, review hash, and event hash;
- an immutable PostgreSQL trigger rejecting update and delete.

The v3 accounting review context binds Candidate version, validation hash, and
validation observation time. Scoped approval creation re-runs S3-02 validation
and persists the approval case, review context, Candidate CAS, and submit event
in one EOS transaction. A WC rejection records the decision and Candidate
return transition in one transaction. Legacy v2 consumers remain compatible;
the new receipt projection is optional and emitted only for v3 reviews.

Migration SHA-256:

```text
eefe1186d9995b1e506c6dcabfe0e621481a00c7335ca8b29c3e4fc73b728ac1
```

## API And Contract

- Query operation: `FINANCE.VOUCHER_CANDIDATE.REVIEW_GET`
- Query endpoint:
  `GET /internal/v2/finance/voucher-candidates/{candidate_id}/review`
- Invalidation operation: `FINANCE.VOUCHER_CANDIDATE.INVALIDATE_REVIEW`
- Invalidation endpoint:
  `POST /internal/v2/finance/voucher-candidates/{candidate_id}/review-invalidation`
- Admission: signed service token and tenant-scoped access

The invalidation request requires exact Candidate version, revision, hash,
approval case, actor, reason, and timezone-aware event time. OpenAPI, positive
examples, JSON Schemas, and a negative missing-reason fixture cover the public
contract. The EOS OpenAPI hash is:

```text
cc98ee6d6d04d5f80aab92a85037ac0e1f7ee4e8f38cf45912e4516c4efb808e
```

## PostgreSQL Protected Smoke

Actual `nex_eos_test` execution passed:

```text
tests: 1 passed, 80 deselected
database: postgresql://nex_eos_user@127.0.0.1:5432/nex_eos_test
migration head: 2535_eos_candidate_review_state
```

The smoke created an isolated schema, ran the real migration chain, inserted a
Candidate and review case, executed `SUBMIT -> RETURN`, verified the immutable
event trigger rejects mutation, dropped the schema, and asserted zero residue.

## Regression And Slice Gate

Focused S3-01 through S3-03 regression passed with `166 passed, 4 skipped`.
The complete NeX-EOS Slice Gate then passed:

```text
status: PASS
commands: 6/6
tests: 1,455 passed, 45 skipped
statement coverage: 96.35% (threshold 96.00%)
branch coverage: 94.22% (threshold 94.00%)
candidate_review.py: statement/branch 100.00%/100.00%
contract validation: PASS (239 schemas, 297 examples, 248 negative, 10 OpenAPI)
Golden Journey transition audit: PASS
demo-to-product dependency audit: PASS
```

Machine-readable evidence:

- `reports/quality/mybee_w30_s3_03_slice_gate.json`

## Next Entry

`MB3-01` may now consume the stable Candidate creation, validation, and review
contracts. `S4-01` must still admit fresh human accounting proof and current OA
authority before any later atomic posting; S3-03 alone never authorizes GL
mutation.
