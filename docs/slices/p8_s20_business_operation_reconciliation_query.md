# P8-S20 EOS BusinessOperation Reconciliation Query

## Outcome

NeX-EOS now exposes a protected, tenant-scoped authoritative query by
`BusinessOperationId`. The projection includes operation and payload identity,
commit state, stable business transaction and Voucher refs, reconciliation
status, and the last observed time.

Stored `COMMITTED` and `NOT_COMMITTED` states are reported only when confirmed.
A durable `PENDING` record is mapped to `UNKNOWN_COMMIT_STATE` with
`RECONCILIATION_REQUIRED`; it never causes an implicit retry. Missing and
cross-tenant operations share the same not-found boundary, while incomplete or
unknown persisted states fail closed as unavailable.

## Verification

- SQLite committed/not-committed/unknown/not-found/cross-tenant/corruption tests
- protected HTTP route success, denial, not-found, and dependency-unavailable tests
- focused S19/S20 regression: 44 passed with 100% statement and branch coverage
  for command, query, and API modules
- EOS Slice Gate: 287 passed; statement coverage 99%, branch coverage 100%
- contract validation: 176 schemas, 238 examples, 207 negative examples, and
  9 OpenAPI documents
