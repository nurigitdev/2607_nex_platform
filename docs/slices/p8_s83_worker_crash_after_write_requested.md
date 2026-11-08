# P8-S83: Worker Crash After WRITE_REQUESTED

## Status

Completed on 2026-10-24. P8-S84 is next.

## Boundary

P8-S83 injects a worker failure after the exact NSL `WRITE_REQUESTED` is
durable and after EOS has committed the attachment-bearing Voucher, but before
the worker retains the provider outcome:

```text
durable AE WRITE_REQUESTED
-> one EOS CREATE dispatch
-> EOS commits Voucher + attachment associations + outbox
-> worker discards COMMITTED outcome and exits
-> independent restart process
-> reload exact AE WRITE_REQUESTED evidence
-> project UNKNOWN_COMMIT_STATE
-> one EOS BusinessOperation reconciliation GET
-> authoritative COMMITTED
-> zero live WRITE redispatch
```

The restart process never treats process loss, a missing in-memory result, or
the existence of WRITE_REQUESTED as proof of `NOT_COMMITTED`.

## Implementation

`WorkerCrashAfterWriteRequestedFaultPort` validates the admitted WRITE request
against the durable AE evidence before one provider dispatch. It records the
request/evidence identity, discards the returned outcome, and raises the
deterministic crash error. A second dispatch through the same fault port fails
closed.

`WorkerRestartAfterWriteRequestedRecovery` has no live WRITE dependency. It
revalidates the restarted request against durable evidence, projects an NSL
`WriteCommitUnknown`, and permits one reconciliation call only. COMMITTED,
NOT_COMMITTED, and still-UNKNOWN are preserved as authoritative outcomes; none
is manufactured from worker-local state.

`p8_s83_write_requested_worker.py` loads the digest-admitted NSL v0.2 wheel and
supports two process-isolated phases:

```text
crash   exit 83 after durable WRITE_REQUESTED and one provider outcome
recover exit 0 after durable evidence validation and EOS reconciliation
```

No production API, event schema, database table, or migration changed.

## Attachment-Bearing Protected Evidence

The protected journey used actual:

```text
nex_ae_test PostgreSQL
nex_wc_test PostgreSQL
nex_oa_test PostgreSQL
nex_eos_test PostgreSQL
rustfs/rustfs:1.0.1@sha256:1803faef57627e2d9c2e7d89d655d712ddded5389040054987163043fecb6a3c
SSE-S3 enabled
digest-admitted nex-skill-language 0.2.0 wheel
```

Three immutable objects were uploaded and locked into one manifest before the
approval and WRITE journey. Crash and restart produced:

```text
crash processes                         = 1
crash process exit code                 = 83
provider CREATE dispatches              = 1
provider state before crash             = COMMITTED
restart processes                       = 1
durable evidence loads                  = 1
authoritative reconciliation GETs       = 1
live WRITE dispatches after restart     = 0
assumed NOT_COMMITTED                   = false
reconciled state                        = COMMITTED
ae_nsl_write_evidence rows              = 1
eos_business_operation rows             = 1
eos_voucher_draft rows                  = 1
eos_voucher_draft_attachment rows       = 3
eos_outbox rows                         = 1
AttachmentManifestHash drift            = 0
attachment ID/object reference drift    = 0
RustFS duplicate object versions        = 0
test DB/object residue                  = 0
```

Protected result:

```text
1 passed
0 skipped
```

Remote generation, embedding, and reranking providers were not required.

## Regression And Quality Gate

Reliability fault regression and coverage:

```text
77 passed
statement coverage = 100.00%
branch coverage    = 100.00%
```

P8 focused regression:

```text
1,652 passed
57 protected opt-in skipped
```

NeX-AE Slice Gate:

```text
pytest                       = 5,373 passed / 45 protected opt-in skipped
statement coverage           = 98.34% / required 95.00%
branch coverage              = 96.32% / required 94.00%
reliability fault scope      = 100.00% statement / 100.00% branch
contract validation          = 191 schemas / 253 positive / 221 negative / 9 OpenAPI
gate commands                = 4 / 4
gate exit                    = 0
```

The protected S83 scenario has separate zero-skip evidence above.

## Exit Decision

P8-S83 closes INV-06 through INV-10 and INV-13 for an attachment-bearing
worker restart. Durable WRITE_REQUESTED is treated as an uncertain boundary,
not as permission to retry and not as proof that nothing committed. P8-S84 may
now revoke package trust, approval authority, and finance mutation authority
at their current protected boundaries.
