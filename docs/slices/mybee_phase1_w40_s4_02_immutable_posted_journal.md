# W40-S4-02 Immutable PostedJournal and Database Protection

## Outcome

PASS / CLOSED. NeX-EOS now has an immutable PostedJournal persistence model,
database-enforced mutation protection, and fresh-authority GET/VERIFY read
boundaries. This Slice does not perform Posting; S4-03 remains the owner of the
atomic Posting transaction.

## Implemented Boundary

- Added migration `2539_eos_posted_journal` and the following EOS-owned tables:
  - `eos_accounting_approval_acceptance`
  - `eos_journal_header`
  - `eos_journal_line`
  - `eos_journal_sequence`
- Kept table and constraint names below PostgreSQL identifier limits.
- Bound each Journal to exactly one immutable Candidate revision, accounting
  approval evidence, approved document, accounting period, BusinessOperation,
  Posting rule release, and one or more Project-attributed lines.
- Required every line to retain Candidate line, account, account-policy,
  Project UUID/code, currency, FX, evidence, and semantic-hash lineage.
- Enforced contiguous lines, same functional currency, exactly one debit or
  credit side, positive balanced totals, and hash-bound header/line/acceptance
  semantics before persistence.
- Added deferred database balance verification so a header and its lines may be
  staged in one transaction while an incomplete or unbalanced commit is denied.
- Added PostgreSQL triggers that reject UPDATE and DELETE on PostedJournal
  header, line, and accounting acceptance records with SQLSTATE `55000`.
- Added uniqueness guards for Candidate revision, period sequence, Journal
  number, BusinessOperation, idempotency key, proof, and acceptance identity.
- Added repository staging that deliberately does not own the transaction. S4-03
  must combine fresh S4-01 admission, sequence allocation, Journal staging,
  BusinessOperation, and outbox publication in one unit of work.

## Read and Verification Boundary

Installed service-token-protected endpoints:

```text
GET /internal/v2/finance/journals/{journal_id}
GET /internal/v2/finance/journals/{journal_id}/verification
```

Both operations require fresh OA `finance:report:read` authority for the
company and fresh Project authorization for every Project represented by the
Journal lines. VERIFY recomputes line hashes, Journal hash, line count,
functional debit/credit totals, and accounting-acceptance binding. Persistence,
authorization, malformed state, and verification failures are fail-closed.

Canonical contracts:

```text
schemas/service/nex_eos/posted_journal.v1.schema.json
schemas/service/nex_eos/journal_verification.v1.schema.json
```

Contract validation:

```text
schemas           = 251
examples          = 308
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

It applied the complete EOS migration inventory to an isolated schema and
proved:

- migration `2539_eos_posted_journal` is applied successfully;
- one balanced Journal, two lines, and one accounting acceptance commit;
- persisted hashes and line count survive a repository round trip;
- header UPDATE and DELETE are rejected with SQLSTATE `55000`;
- line UPDATE and DELETE are rejected with SQLSTATE `55000`;
- accounting-acceptance UPDATE and DELETE are rejected with SQLSTATE `55000`;
- duplicate Candidate/proof/Journal persistence is rejected; and
- the isolated schema is dropped with zero residue.

Execution results:

```text
S4-01 + S4-02 protected PostgreSQL smoke = 2 passed, 101 deselected
```

Remote embedding, reranking, and generation providers were not required.

## Regression and Coverage

Focused regression:

```text
190 passed, 5 protected-smoke skips
```

New Journal-focused tests cover valid domestic and foreign-currency lines,
malformed scalar/FX/hash/identity input, balance and lineage rejection,
repository conflict/corruption/unavailability, fresh OA and Project denial,
tamper detection, installed API fail-closed wiring, and timezone-aware
verification.

Focused new-module coverage:

```text
journal_verification.py = 100%
journals.py              = 94%
combined                 = 96%
```

## Slice Gate

Machine-readable evidence:

```text
reports/quality/mybee-w40-s4-02-slice-gate.json
```

Final result:

```text
tests               = 1728 passed, 51 protected-smoke skips
statement coverage  = 96.68% (threshold 95.00%)
branch coverage     = 94.92% (threshold 94.00%)
commands            = 5/5 passed
contract validation = PASS
transition audit    = PASS
dependency audit    = PASS
```

## Entry Decision

```text
W40-S4-02 = PASS / CLOSED
W40-S4-03 = AUTHORIZED
```

S4-03 may implement atomic Candidate-to-Journal Posting using the S4-01 fresh
admission receipt and this Slice's transaction-local repository. It must not
add an UPDATE or DELETE path to PostedJournal records.
