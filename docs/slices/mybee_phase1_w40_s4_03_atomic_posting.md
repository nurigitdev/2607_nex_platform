# W40-S4-03 Atomic Posting in a Single EOS Transaction

## Outcome

PASS / CLOSED. NeX-EOS now converts one admitted `READY_FOR_REVIEW`
VoucherCandidate revision into an immutable PostedJournal in one database
transaction. Candidate state, Journal records, document consumption,
BusinessOperation, idempotency evidence, and outbox publication cannot commit
independently.

## Atomic Boundary

The installed operation is:

```text
POST /internal/v2/finance/voucher-candidates/{candidate_id}/posting
operation = FINANCE.VOUCHER.APPROVE_AND_POST
event     = FINANCE.JOURNAL_POSTED.v1
```

Before opening the mutation boundary, the service performs current Candidate
validation and S4-01 fresh OA/Project accounting admission. Inside the single
EOS unit of work it then:

1. revalidates the short-lived admission receipt and locks the Candidate;
2. locks and verifies the OPEN AccountingPeriod;
3. rechecks account policy, PostingRule, document, accounting proof, and FX
   lineage against authoritative EOS rows;
4. allocates the period-local Journal sequence under lock;
5. stages immutable accounting acceptance, Journal header, and Journal lines;
6. consumes the approved document amount;
7. changes the Candidate from `READY_FOR_REVIEW` version 2 to `POSTED` version
   3 with compare-and-swap semantics; and
8. commits BusinessOperation, idempotency evidence, and the versioned outbox
   event through the existing transaction coordinator.

No network call occurs inside this transaction. Any stale authority, period,
policy, proof, document, FX state, persistence error, or Candidate race aborts
the complete transaction.

## Replay and Failure Semantics

- The canonical NSL-compatible payload hash binds Candidate revision, expected
  version/hash, company, and accounting evidence.
- Exact replay returns the committed result with `REPLAYED` and creates no
  second Journal, consumption, sequence, or outbox record.
- Reused operation or idempotency identity with different semantics fails
  closed.
- A commit that wins between initial replay lookup and fresh validation is
  recognized as an exact replay instead of being misclassified as stale.
- Fault injection after Journal staging, document consumption, and Candidate
  transition proves rollback to the unchanged `READY_FOR_REVIEW` state.

## Persistence and Contracts

Migration `2540_eos_atomic_journal_posting`:

- admits the terminal Candidate state `POSTED`;
- admits canonical versioned Journal outbox event names;
- binds document consumption to the exact Candidate revision; and
- adds a deferred link from consumption to the immutable PostedJournal.

Canonical contracts:

```text
schemas/service/nex_eos/journal_post_command.v1.schema.json
schemas/service/nex_eos/journal_post_result.v1.schema.json
examples/service/eos_journal_post_command.v1.json
examples/service/eos_journal_post_result.committed.json
```

The validation projection now exposes `accounting_rule_profile_hash`, allowing
Posting to reconstruct and verify the exact validation semantics approved by
the accounting decision.

Contract validation:

```text
schemas           = 253
examples          = 310
negative_examples = 256
openapi           = 10
result            = PASS
```

## Actual PostgreSQL Evidence

The protected smoke connected directly to:

```text
database = nex_eos_test
user     = nex_eos_user
```

Each case applied the complete EOS migration inventory to an isolated schema.
The combined S4-01/S4-02/S4-03 run proved fresh admission, immutable Journal
protection, atomic Posting, exact replay, one header, two lines, one document
consumption, one sequence allocation, and terminal Candidate state `POSTED`.
Every isolated schema was dropped and verified absent afterward.

```text
protected PostgreSQL smoke = 3 passed, 120 deselected
```

Remote embedding, reranking, and generation providers were not required.

## Regression and Coverage

Focused Candidate, FX, business transaction, and contract regression:

```text
203 passed, 7 protected-smoke skips
```

The new Posting module covers malformed commands, stale validation/proof,
missing Candidate/revision/document, closed period, changed policy/currency,
missing FX, replay lookup failure, incomplete replay, concurrent replay,
transaction absence, persistence failure, sequence reuse, and rollback.

```text
journal_posting.py coverage = 99%
```

## Slice Gate

Machine-readable evidence:

```text
reports/quality/mybee-w40-s4-03-slice-gate.json
```

Final result:

```text
tests               = 1778 passed, 52 protected-smoke skips
statement coverage  = 96.74% (threshold 95.00%)
branch coverage     = 95.00% (threshold 94.00%)
commands            = 5/5 passed
contract validation = PASS
transition audit    = PASS
dependency audit    = PASS
```

The final branch result is above the S4-02 baseline of 94.92%.

## Entry Decision

```text
W40-S4-03 = PASS / CLOSED
```

The next W40 Slice may consume the committed PostedJournal and
`FINANCE.JOURNAL_POSTED.v1` event. It must not introduce UPDATE or DELETE paths
for PostedJournal or accounting acceptance records.
