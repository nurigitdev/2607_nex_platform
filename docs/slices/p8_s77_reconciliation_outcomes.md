# P8-S77: Reconciliation Outcomes

## Status

Completed on 2026-10-24. P8-S78 is next.

## Boundary

P8-S77 closes the authoritative read-only transition from an admitted NSL v0.2
`WriteCommitUnknown` outcome:

```text
UNKNOWN_COMMIT_STATE -> COMMITTED
UNKNOWN_COMMIT_STATE -> NOT_COMMITTED
UNKNOWN_COMMIT_STATE -> UNKNOWN_COMMIT_STATE
```

Reconciliation issues only EOS BusinessOperation `GET` requests. It never
repeats the Voucher CREATE command, attachment association mutation, manifest
lock, or RustFS upload. A missing, unavailable, malformed, or contradictory
authoritative response remains `UNKNOWN_COMMIT_STATE`; it never implies
`NOT_COMMITTED`.

## Implementation

The existing `HttpEosReconciliationAdapter` and EOS BusinessOperation query
remain the system boundary. No API field, database table, or migration changed.

The AE adapter now extracts the original attachment lineage from admitted NSL
WRITE arguments and compares a `COMMITTED` projection against the exact:

```text
AttachmentBatchId
AttachmentManifestHash
canonical attachment ID set
```

The admitted NSL runtime freezes argument sequences as tuples, while unit
fixtures may use lists. Both representations are accepted and normalized to
the same sorted unique identity set. Any missing, malformed, duplicate, or
drifted lineage keeps the outcome unknown with
`EOS_RECONCILIATION_RESPONSE_UNTRUSTWORTHY`.

The full payload, including immutable object references, remains bound by the
unchanged NSL `PayloadHash`. The protected test additionally compares every
object reference and RustFS object version before and after reconciliation.

## Protected Acceptance

The protected scenario uses the admitted NSL v0.2 wheel and actual:

```text
nex_ae_test PostgreSQL
nex_wc_test PostgreSQL
nex_oa_test PostgreSQL
nex_eos_test PostgreSQL
rustfs/rustfs:1.0.1@sha256:1803faef57627e2d9c2e7d89d655d712ddded5389040054987163043fecb6a3c
SSE-S3 enabled
```

It uploads and locks three immutable evidence objects, obtains one approval,
injects one post-commit ACK loss, and then resolves three authoritative EOS
states. `NOT_COMMITTED` and `PENDING` are test-seeded legal EOS states used only
to exercise the read model; no business WRITE is bypassed.

```text
protected pytest                       = 1 passed / 0 skipped
EOS CREATE dispatches                  = 1
UNKNOWN -> COMMITTED                   = PASS
UNKNOWN -> NOT_COMMITTED               = PASS
UNKNOWN -> still UNKNOWN               = PASS
Voucher mutation count                 = 1
Voucher attachment associations        = 3
EOS outbox rows                         = 1
BusinessOperation rows                 = 3 (one per queried outcome)
AttachmentManifestHash drift           = 0
attachment ID/object reference drift   = 0
RustFS duplicate object versions       = 0
test DB/object residue                  = 0
```

Remote generation, embedding, and reranking providers were not required.

## Quality Evidence

Focused reconciliation coverage:

```text
tests                              = 69 passed
nsl_eos_reconciliation statement  = 100.00%
nsl_eos_reconciliation branch     = 100.00%
```

NeX-AE Slice Gate:

```text
pytest              = 5,299 passed / 43 protected opt-in skipped
statement coverage  = 98.32% / required 95.00%
branch coverage     = 96.28% / required 94.00%
changed scope       = 100.00% statement / 100.00% branch
contract validation = 191 schemas / 253 positive / 221 negative / 9 OpenAPI
gate exit            = 0
```

Coverage evidence is stored at
`reports/quality/p8-s77-slice.json`.

## Exit Decision

The three reconciliation outcomes are deterministic, tenant-scoped, and
attachment-aware. Exactly one Voucher exists after the matrix, and no recovery
read recreates business or object state. P8-S78 may now validate deterministic
post-write verification failure while preserving the committed Voucher and its
exact attachment associations.
