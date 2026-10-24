# P8-S80: Outbox Publication ACK Loss

## Status

Completed on 2026-10-24. P8-S81 is next.

## Boundary

P8-S80 separates committed business state from later event delivery:

```text
one EOS Voucher mutation + three attachment associations + one outbox row
-> downstream accepts the outbox event
-> publication ACK is lost
-> outbox remains PENDING with attempt_count = 1
-> retry the same event_id and payload hash only
-> confirmed ACK marks the outbox PUBLISHED with attempt_count = 2
```

Neither publication attempt calls the business transaction coordinator.
Voucher mutation, attachment association, approval, manifest, and object upload
therefore remain outside the retry boundary.

## Source Audit and Implementation

P8-S09 already created `eos_outbox` atomically with the business mutation and
provided the required `PENDING/PUBLISHED`, `attempt_count`, `updated_at`, and
`published_at` fields. No new table or migration was needed.

`nex_eos.outbox_publication` adds:

- typed event, transport receipt, publication result, and error contracts;
- `SqlAlchemyEosOutboxPublisher.publish_next()`;
- tenant-scoped oldest-first selection;
- PostgreSQL `FOR UPDATE SKIP LOCKED` serialization;
- event payload hash and receipt identity validation;
- `PENDING` plus incremented attempt count when an ACK is unconfirmed;
- `PUBLISHED` only after an exact event/hash-bound receipt.

The row lock is held across one transport attempt. A transport failure or
invalid receipt records a retryable publication outcome without changing the
committed business operation. A malformed persisted event fails closed before
publication.

`EosOutboxAckLossFaultTransport` accepts the event through an idempotent sink,
discards the first ACK as `TimeoutError`, and allows the second ACK through.
It records publication attempts, downstream acceptances, acknowledged
attempts, and unique semantic event count.

## Protected Evidence

The protected scenario used actual:

```text
nex_ae_test PostgreSQL
nex_wc_test PostgreSQL
nex_oa_test PostgreSQL
nex_eos_test PostgreSQL
rustfs/rustfs:1.0.1@sha256:1803faef57627e2d9c2e7d89d655d712ddded5389040054987163043fecb6a3c
SSE-S3 enabled
```

It uploaded and locked three immutable evidence objects, obtained WC approval
bound to the manifest, committed one Voucher through the EOS API, and then
exercised ACK loss and publication retry through the SQL publisher.

```text
EOS Voucher CREATE requests          = 1
outbox publication attempts          = 2
downstream acceptances               = 2
confirmed acknowledgements           = 1
unique semantic event IDs            = 1
final outbox delivery_state           = PUBLISHED
final outbox attempt_count            = 2
eos_business_operation rows           = 1
eos_voucher_draft rows                = 1
eos_voucher_draft_attachment rows     = 3
eos_outbox rows                       = 1
AE attachment batches                 = 1
AE attachment rows                    = 3
WC approval work items                = 1
WC approval decisions                 = 1
manifest/attachment/object drift      = 0
RustFS object versions per key        = 1
test DB/object/container residue      = 0
```

Protected result:

```text
1 passed
0 skipped
```

Remote generation, embedding, and reranking providers were not required.

## Regression and Quality Gate

Focused EOS/P8 WRITE, attachment, approval, reconciliation, verification, and
reliability regression:

```text
848 passed
26 protected opt-in skipped
```

The NeX-EOS Slice Gate completed with:

```text
pytest                         = 630 passed / 18 protected opt-in skipped
statement coverage             = 99.12% / required 95.00%
branch coverage                = 98.49% / required 94.00%
outbox publisher coverage      = 97.90% statement / 96.67% branch
reliability fault coverage     = 100.00% statement / 100.00% branch
contract validation            = 191 schemas / 253 positive / 221 negative / 9 OpenAPI
gate exit                      = 0
```

The protected S80 scenario has separate zero-skip evidence above.

## Exit Decision

P8-S80 is closed. An outbox publication ACK loss retries the exact event only;
it cannot repeat Voucher mutation, attachment association writes, approval,
manifest creation, or RustFS upload. P8-S81 may now exercise approval-event
ACK loss and prove at-most-once semantic resume behavior.
