# W40-S4-04 Posting Replay, Outbox, and UNKNOWN Recovery

## Outcome

PASS / CLOSED. NeX-EOS now exposes an authoritative reconciliation boundary
for a committed Journal posting, publishes a typed
`FINANCE.JOURNAL_POSTED.v1` event, and distinguishes committed, not committed,
unknown, and verification-failed outcomes without mutating the immutable GL.

## Source and Persistence Decision

The source audit confirmed that S4-03 already persists every authoritative
fact needed by this Slice:

- `eos_business_operation` records the committed operation and result binding;
- `eos_idempotency` binds the operation identity to the canonical payload hash;
- immutable Journal header, lines, and accounting acceptance record the GL;
- `eos_outbox` records publication state and the versioned event payload.

S4-04 therefore reuses migration `2540_eos_atomic_journal_posting` and adds no
table or migration. A separate reconciliation table would duplicate the
authoritative operation state and introduce an avoidable consistency problem.

## Runtime Boundary

The installed read boundary is:

```text
GET /internal/v2/finance/business-operations/{business_operation_id}/journal-status
operationId = FINANCE.JOURNAL.RECONCILE
```

The service validates tenant and operation identity, reads all records in one
database session, and returns one of the following outcomes:

| Outcome | Verification | Meaning |
|---|---|---|
| `COMMITTED_CONFIRMED` | `VERIFIED` | Operation, idempotency, immutable Journal, acceptance, result, and outbox lineage agree. |
| `UNKNOWN_COMMIT_STATE` | `RECONCILIATION_REQUIRED` | The operation is pending or its authoritative commit state is not yet available. |
| `NOT_COMMITTED_CONFIRMED` | `NOT_APPLICABLE` | The operation is terminally failed and no Journal was committed. |
| `COMMITTED_VERIFICATION_FAILED` | `FAILED` | A committed operation has missing or conflicting immutable lineage and fails closed. |

`UNKNOWN_COMMIT_STATE` is returned as HTTP `202`; resolved outcomes use HTTP
`200`. Unknown operation identities remain HTTP `404`. Reconciliation never
reposts, repairs, updates, or deletes a Journal.

## Event Contract

`FINANCE.JOURNAL_POSTED.v1` now carries the minimum immutable lineage required
for safe consumer replay:

```text
tenant_id
business_operation_id
company_id
journal_id
journal_number
journal_content_hash
candidate_id / candidate_revision
accounting_acceptance_id
accounting_period_id
project_codes
commit_status
posted_at
```

Both event construction and event admission are strict. Missing fields,
invalid identifiers, a non-`COMMITTED` status, duplicate project codes, and
non-canonical project ordering fail closed. The outbox publisher can retry the
same row without changing the business event identity or creating a second
Journal.

Canonical contracts added in this Slice:

```text
contracts/schemas/service/nex_eos/journal_posted_event.v1.schema.json
contracts/schemas/service/nex_eos/journal_reconciliation.v1.schema.json
contracts/examples/service/eos_journal_posted_event.v1.json
contracts/examples/service/eos_journal_reconciliation.committed.json
contracts/examples/service/eos_journal_reconciliation.unknown.json
```

Contract validation completed with:

```text
schemas           = 255
examples          = 313
negative_examples = 257
openapi           = 10
result            = PASS
```

## Replay and Recovery Evidence

`tests/test_nex_eos_mybee_posting_replay_pg.py` proves the canonical SRS
matrix:

- `T-ACID-05`: an ACK lost after commit is recovered by operation lookup and
  exact replay returns the same Journal ID;
- `T-ACID-06`: 20 concurrent calls with one idempotency key and payload hash
  create exactly one Journal;
- `T-ACID-07`: the same key with a different payload hash returns conflict and
  leaves the committed GL unchanged;
- `T-ACID-12`: outbox publication failure after GL commit retains the Journal,
  exposes stale delivery state, and later publishes the same event safely.

Additional regression covers pending and failed operations, missing Journal or
outbox state, result/event/idempotency lineage drift, malformed event payloads,
API status mapping, and persistence-error translation.

## Actual PostgreSQL Evidence

The protected smoke connected directly to:

```text
database = nex_eos_test
user     = nex_eos_user
```

It applied the complete EOS migration inventory to an isolated schema and ran
the 20-call concurrency case, exact replay, conflicting replay, outbox outage,
publisher retry, and authoritative reconciliation. The schema was dropped and
verified absent after the run.

```text
protected PostgreSQL smoke = 31 passed, 0 skipped
```

Remote embedding, reranking, and generation providers were not required.

## Regression and Coverage

Focused non-smoke regression:

```text
30 passed, 1 protected-smoke skip
```

New recovery modules:

```text
journal_operations.py      statement/branch = 100%
journal_outbox_events.py   statement/branch = 100%
```

## Slice Gate

Machine-readable evidence:

```text
reports/quality/mybee-w40-s4-04-slice-gate.json
```

Final result:

```text
tests               = 1808 passed, 53 protected-smoke skips
statement coverage  = 96.78% (threshold 95.00%)
branch coverage     = 95.04% (threshold 94.00%)
commands            = 5/5 passed
contract validation = PASS
transition audit    = PASS
dependency audit    = PASS
```

Branch coverage remains above the S4-03 baseline of 95.00%.

## Entry Decision

```text
W40-S4-04 = PASS / CLOSED
```

The next accounting Slice may consume the typed reconciliation projection and
`FINANCE.JOURNAL_POSTED.v1` event. It must preserve the immutable PostedJournal
boundary and must not interpret an UNKNOWN outcome as permission to post with
a new key.
