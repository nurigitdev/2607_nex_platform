# W40-S4-01 Accounting Proof Admission and Fresh OA Revalidation

## Outcome

PASS / CLOSED. NeX-EOS now admits an exact, current `VoucherCandidate` for
future Posting only after accounting-proof lineage, Human SoD, fresh OA
authority, and Project authorization have all been revalidated.

## Implemented Boundary

- Added canonical operation
  `FINANCE.VOUCHER.APPROVE_AND_POST.ADMISSION`.
- Reused the existing Candidate, immutable revision, review event, accounting
  review context, approval case/decision, policy stage, and
  `eos_accounting_approval_evidence` records.
- Added no migration, Journal table, duplicate approval engine, or final
  Posting acceptance record.
- Required an exact Candidate version, revision, and semantic hash together
  with the exact accounting approval evidence identity.
- Rejected `DOCUMENT_SIGNOFF` evidence, non-final approval, stale validation or
  review lineage, malformed business-approver lineage, and Human SoD conflicts.
- Reloaded the final accounting role from the admitted approval policy stage
  and revalidated the Human approver against fresh OA effective authorization.
- Required fresh Project authorization for `finance:journal:approve` using the
  stable Project code and allowed only `ACTIVE` or `CLOSING` Projects.
- Performed no OA or Project network call while an EOS database transaction was
  open. A second database snapshot detects drift after the external checks.
- Issued a semantic-hash-bound admission receipt with a 30-second default TTL.
  `NEX_EOS_ACCOUNTING_POSTING_ADMISSION_TTL_SECONDS` may configure 1-300
  seconds.
- The receipt is not a transferable bearer credential. S4-03 must invoke fresh
  admission in its server-side composition and pass the resulting receipt
  directly into the local transaction; it must not trust a client-supplied
  receipt as independent Posting authority.
- Added `require_current_in_session()` so S4-03 can lock the proof and Candidate
  and recheck the receipt inside the future atomic Posting transaction.

## API and Contract

Installed endpoint:

```text
POST /internal/v2/finance/voucher-candidates/{candidate_id}/posting-admission
```

The route is service-token protected and fails closed when database, OA, or
Project authorization dependencies are unavailable. JSON Schema, OpenAPI,
positive examples, and a missing-proof negative example were added.

Contract validation:

```text
schemas           = 249
examples          = 306
negative_examples = 256
openapi            = 10
result             = PASS
```

## Verification

Focused regression:

```text
197 passed, 5 protected-smoke skips
```

The new service tests cover successful admission and transaction-local recheck,
OA denial/unavailability/malformed responses, Project denial/unavailability and
status checks, purpose and lineage mismatch matrices, Human SoD, expiry,
tampering, concurrent drift, strict request validation, dependency wiring, and
the installed API fail-closed path.

Focused production-module coverage:

```text
accounting_posting_admission.py
statement/branch combined = 99%
```

## Actual PostgreSQL Evidence

The protected smoke connected to the real EOS test database:

```text
database = nex_eos_test
user     = nex_eos_user
```

It applied the real migration inventory to an isolated schema and proved:

- exact current Candidate, validation, review, approval, and evidence admission;
- transaction-local receipt and row-lock revalidation;
- fresh OA revocation is rejected with HTTP-equivalent 403 semantics;
- `eos_journal_header` and `eos_journal_line` are not created prematurely; and
- the isolated schema is dropped with zero residue.

Execution result:

```text
1 passed, 101 deselected
```

Remote embedding, reranking, and generation providers were not required.

## Slice Gate

Machine-readable evidence:

```text
reports/quality/mybee-w40-s4-01-slice-gate.json
```

Final result:

```text
tests               = 1685 passed, 50 protected-smoke skips
statement coverage  = 96.74% (threshold 95.00%)
branch coverage     = 94.99% (threshold 94.00%)
commands            = 5/5 passed
contract validation = PASS
transition audit    = PASS
dependency audit    = PASS
```

## Entry Decision

```text
W40-S4-01 = PASS / CLOSED
W40-S4-02 = AUTHORIZED
```

S4-02 may add immutable PostedJournal persistence. S4-03 must consume this
receipt and call the transaction-local recheck in the same unit of work that
creates the Journal; this Slice alone does not authorize or perform Posting.
