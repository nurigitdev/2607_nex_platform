# W40-S4-00A Pre-Posting Candidate Revision Closure

## Outcome

PASS / CLOSED. `VoucherCandidate` remains the sole pre-Posting voucher SoR,
returned corrections now append immutable revisions, and the future Journal
namespace remains reserved for PostedJournal.

## Implemented Boundary

- Added canonical operation `FINANCE.VOUCHER_CANDIDATE.REVISE`.
- Added a full-replacement correction contract bound to Candidate
  version/revision/hash and the exact immutable return event.
- Reused `eos_voucher_candidate`, `eos_voucher_candidate_revision`,
  `eos_voucher_candidate_line`, BusinessOperation, idempotency, review-event,
  and outbox persistence.
- Added no migration and no `journal_inbox` table.
- Appended revision `N+1`, preserved all older revisions/lines, and advanced
  only header state/current revision/version/timestamp by CAS.
- Required a fresh OA finance scope and Project authorization before local
  mutation.
- Blocked validation or review submission directly from
  `RETURNED_FOR_CORRECTION`.
- Added installed EOS API, dependency wiring, OpenAPI, JSON Schemas, positive
  and negative examples, and `VOUCHER_CANDIDATE_REVISED` outbox emission.

## Focused Verification

```text
tests/test_nex_eos_mybee_voucher_candidate.py
  - append-only revision and old-revision preservation
  - exact replay and changed-replay conflict
  - semantic no-op and stale return-event rejection
  - malformed contract matrix
  - authorization, payload-hash, and transaction fail-closed branches
  - authenticated API and unavailable-dependency behavior

voucher_candidate_revision_commands.py focused coverage
  statement/branch combined report: 95%

contract_validation=pass
  schemas=247
  examples=304
  negative_examples=255
  openapi=10
```

## Actual PostgreSQL Evidence

Target identity was verified before execution:

```text
database = nex_eos_test
user     = nex_eos_user
```

The protected smoke used a unique schema, applied the real EOS migration
inventory, and proved:

- two concurrent corrections from revision 1 produced one commit and one
  `EOS_VOUCHER_CANDIDATE_REVISION_STALE` conflict;
- exact replay returned the same revision 2 identity;
- revision 1 hash remained unchanged;
- raw SQL `UPDATE` and `DELETE` of revision and line rows were rejected by
  PostgreSQL triggers;
- exactly one `VOUCHER_CANDIDATE_REVISED` event was emitted;
- `eos_journal_header` and `eos_journal_line` did not exist prematurely; and
- the isolated schema was dropped and `to_regnamespace` returned null.

Execution:

```bash
NEX_EOS_TEST_DATABASE_URL='postgresql+psycopg://.../nex_eos_test' \
NEX_EOS_MYBEE_W40_S4_00A_POSTGRES_SMOKE=1 \
./.venv/bin/pytest -q tests/test_nex_eos_mybee_voucher_candidate.py \
  -k actual_postgres_candidate_revision_race_immutability_and_zero_residue
```

Result: `1 passed`.

## Slice Gate

The final NeX-EOS Slice Gate runs the complete service regression, contract
validation, transition audit, and dependency audit. Its machine-readable
coverage receipt is written to:

```text
reports/quality/mybee-w40-s4-00a-slice-gate.json
```

Final result:

```text
tests                 = 1643 passed, 49 protected-smoke skips
statement coverage    = 96.72% (threshold 95.00%)
branch coverage       = 94.93% (threshold 94.00%)
commands              = 5/5 passed
contract validation   = PASS
transition audit      = PASS
dependency audit      = PASS
```

Remote embedding, reranking, and generation providers were not required.

## Entry Decision

```text
W40-S4-00A = PASS / CLOSED
W40-S4-01  = AUTHORIZED
```

W40-S4-01 may now consume only an exact current Candidate revision and fresh
validation/review evidence. PostedJournal persistence remains owned by the
later S4-02/S4-03 boundary.
