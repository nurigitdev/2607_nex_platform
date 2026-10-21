# P8-S19 EOS Create Voucher Draft Service

## Outcome

The canonical `FINANCE.CREATE_VOUCHER_DRAFT` endpoint is executable. It parses
the P8-S18 contract, reconstructs and verifies the canonical business payload
hash, performs fresh P8-S17 OA authorization, and then commits the Voucher,
lines, optional attachment associations, BusinessOperation, idempotency result,
and outbox event in one SQLAlchemy transaction.

The existing Voucher and attachment repositories now expose session-bound
write methods so the coordinator owns the transaction without duplicating
their domain and object-reference validation. Their original standalone APIs
remain compatible.

Authorization denial, hash mismatch, Project/Account/balance failure, object
resolver failure, and idempotency semantic conflict are fail-closed. A rollback
leaves no partial Voucher or business-control record. Replay performs fresh
authorization and returns the original committed Voucher identity.

## Verification

- focused SQLite transaction, rollback, idempotency, parser, attachment, and
  protected route regression: 33 passed; new command/API statement and branch
  coverage 100%/100%
- refactored transaction-boundary regression: 128 passed with 100% statement
  and branch coverage across BusinessOperation, Voucher, attachment, and command
- EOS Slice Gate: 276 passed; statement coverage 99%, branch coverage 100%
- no database migration or remote model provider is required
