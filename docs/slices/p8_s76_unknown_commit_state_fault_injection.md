# P8-S76: UNKNOWN_COMMIT_STATE Fault Injection

## Status

Completed on 2026-10-24. P8-S77 is next.

## Boundary

P8-S76 deliberately loses one accepted EOS response after EOS has committed
the command. It proves the ambiguity boundary only:

```text
WRITE_REQUESTED
-> one EOS CREATE dispatch
-> EOS commits Voucher + attachment associations + outbox
-> accepted response is discarded
-> AE observes UNKNOWN_COMMIT_STATE
-> RECONCILIATION_REQUIRED
-> no blind CREATE retry
```

P8-S76 does not query EOS to resolve the unknown state. The three
authoritative reconciliation outcomes belong to P8-S77.

## Implementation

`scripts/smoke/p8_reliability_faults.py` provides a reusable
`EosCommitAckLossFaultPort`. It delegates through `execute_raw()` exactly once,
accepts only a trustworthy `200` or `201` response, discards that response,
and projects an admitted NSL `WriteCommitUnknown` outcome. A second invocation
fails before reaching EOS.

The older P8-S67 Golden A retry worker now reuses this adapter instead of
maintaining a private duplicate. No production API, database schema, or
migration changed.

## Acceptance

Unit regression proves:

- accepted `200` and `201` responses become `UNKNOWN_COMMIT_STATE`;
- evidence explicitly records `RECONCILIATION_REQUIRED`;
- a second call cannot reach the delegate;
- non-committed or contradictory responses cannot activate the fault;
- malformed dependencies and malformed outcomes fail closed.

The protected scenario uses the digest-admitted NSL v0.2 wheel in its existing
process-isolated profile and runs against:

```text
nex_ae_test PostgreSQL
nex_wc_test PostgreSQL
nex_oa_test PostgreSQL
nex_eos_test PostgreSQL
rustfs/rustfs:1.0.1@sha256:1803faef57627e2d9c2e7d89d655d712ddded5389040054987163043fecb6a3c
SSE-S3 enabled
```

It uploads and locks three immutable objects, obtains an approval bound to the
manifest, dispatches the actual attachment-bearing EOS command once, and then
injects ACK loss. Assertions after the lost response are:

```text
observed commit state            = UNKNOWN_COMMIT_STATE
required action                  = RECONCILIATION_REQUIRED
EOS dispatch attempts            = 1
eos_business_operation rows      = 1
eos_voucher_draft rows           = 1
eos_voucher_draft_attachment     = 3
eos_outbox rows                  = 1
AttachmentManifestHash changed   = false
attachment IDs changed           = false
RustFS object refs changed       = false
RustFS object versions per key   = 1
test DB/object residue           = 0
```

Protected result:

```text
1 passed
0 skipped
```

Remote generation, embedding, and reranking providers were not required.

The NeX-AE Slice Gate then completed with:

```text
pytest              = 5,282 passed / 43 protected opt-in skipped
statement coverage  = 98.32% / required 95.00%
branch coverage     = 96.28% / required 94.00%
fault adapter scope = 100.00% statement / 100.00% branch
contract validation = 191 schemas / 253 positive / 221 negative / 9 OpenAPI
gate exit            = 0
```

The S76 protected scenario has separate zero-skip evidence above.

## Exit Decision

INV-01, INV-06, INV-07, INV-08, INV-09, and INV-10 are proven for the
attachment-bearing ACK-loss boundary. P8-S77 must now use authoritative EOS
reads to prove `UNKNOWN -> COMMITTED`, `UNKNOWN -> NOT_COMMITTED`, and
`UNKNOWN -> still UNKNOWN` without mutating the Voucher, manifest, or objects.
