# P8-S21 EOS Verification Read API

## Outcome

NeX-EOS now exposes a service-protected, side-effect-free Voucher verification
read for NSL `PostWriteVerification`. It requires exact tenant, `VoucherRef`,
and `BusinessOperationId`, then proves a committed binding before returning the
stable Voucher state, Project ref, version, line/attachment counts, exact zero
balance, payload hash, and deterministic stable-business-state hash.

Missing or cross-tenant records collapse to not-found. Pending operations,
mismatched operation/Voucher lineage, missing lines, invalid balance, and
corrupt dates/timestamps fail closed. The implementation contains SELECT-only
queries; regression instrumentation asserts zero mutation statements during
verification.

## Verification

- Focused S19-S21 SQLite regression: 55 passed; relevant modules reached 100%
  statement and branch coverage.
- EOS Slice Gate: 298 passed; statement coverage 99% and branch coverage 100%.
- Contract validation: 176 schemas, 238 examples, 207 negative examples, and
  9 OpenAPI documents.
- The first repository Checkpoint Gate exposed four legacy tests with fixed
  contract totals from before P8-S18. The tests now compare successful
  validation counts with the current file/index inventory instead of replacing
  one stale constant with another.
- Repeated repository Checkpoint Gate: 15,140 passed and 56 protected skips;
  statement coverage 98.72% and branch coverage 97.19%.
- PostgreSQL execution remains intentionally reserved for the P8-S22 protected
  foundation gate.
