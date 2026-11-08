# P8-S09: EOS BusinessOperation / Idempotency / Outbox Core

Completed on 2026-10-21. NeX-EOS now owns the durable transaction core that
later organization, project, account, and Voucher slices can join without
creating another idempotency or outbox implementation.

## Scope

- Added migration `2501_eos_business_transaction_core`.
- Added `eos_business_operation`, `eos_idempotency`, and `eos_outbox`.
- Added in-memory and SQLAlchemy EOS transaction coordinators.
- Wired the SQL coordinator into the EOS application whenever its database
  runtime is configured.
- Kept public domain routes, Voucher tables, delivery workers, reconciliation,
  and JobQueue behavior outside this Slice.

## Transaction Contract

The caller supplies the stable `BusinessOperationId`; EOS validates and stores
it without deriving a replacement. The semantic identity is tenant-qualified
and protected by both:

```text
(tenant_id, business_operation_id)
(tenant_id, idempotency_key)
```

An exact duplicate with the same key, BusinessOperationId, operation, payload
hash, and event type returns the original result and outbox identities without
executing the mutation again. Any inconsistent binding fails closed with
`EOS_IDEMPOTENCY_CONFLICT` and performs no duplicate mutation.

The production coordinator inserts pending operation/idempotency records,
executes the caller's domain mutation using the same SQLAlchemy session,
finalizes both records, and inserts the outbox event in one transaction. An
exception or failed constraint rolls back all participating business and core
records. A unique-key race is re-read after rollback so one request creates the
transaction and exact competitors reuse it.

## Event Safety

P8-S09 enables `BUSINESS_TRANSACTION_COMMITTED` and
`VOUCHER_DRAFT_CREATED`. The outbox payload contains only schema version,
tenant, BusinessOperationId, operation, and an optional bounded business result
reference. The full business result remains in the operation/idempotency
records and is not copied into the event. Each event receives a canonical
SHA-256 semantic hash.

## Database Integrity

The migration enforces UUID identities, tenant-qualified uniqueness, bounded
operation and key lengths, `sha256:` hash shape, JSON-object results, state
transitions, non-negative attempts, foreign keys, and pending/published outbox
consistency. All new table, constraint, and index names remain below the
PostgreSQL 63-byte identifier limit.

## Verification

- EOS S07-S09 focused regression: `68 passed`.
- Shared migration/database/tooling regression: `78 passed`.
- EOS Slice Gate: statement coverage `100%`, branch coverage `100%`.
- Contract validation: 174 schemas, 236 examples, 204 negative examples, and
  9 OpenAPI documents.
- Actual dev migration applied `2501` once and skipped `2500/2501` on rerun.
- Actual test migration applied `2501` once and skipped `2500/2501` on rerun.
- S08 protected migration/reset smoke passed after the S09 FK tables existed.
- S09 protected PostgreSQL smoke passed against
  `nex_eos_user@nex_eos_test`.
- Eight simultaneous exact requests produced one business mutation, one
  BusinessOperation, one idempotency result, and one outbox event; seven calls
  reused the original result.
- A forced business mutation failure left zero operation, idempotency, outbox,
  and business-probe rows.
- Final test DB row counts were `0/0/0`; no temporary schema or probe table
  remained.
- Remote model providers were not required.

The Platform Full Gate was not repeated. P8-S09 follows the Slice Gate cadence;
the P8 wave-closing Slice will run the Full Gate.
