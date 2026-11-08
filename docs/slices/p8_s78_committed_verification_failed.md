# P8-S78: COMMITTED + Verification FAILED

## Status

Completed on 2026-10-24. P8-S79 is next.

## Boundary

P8-S78 proves that deterministic post-WRITE verification failure does not
change an already committed business outcome:

```text
one EOS CREATE dispatch
-> Voucher + attachment associations + outbox COMMITTED
-> one healthy authoritative EOS read-back
-> deterministic verification mismatch injected
-> VerificationStatus FAILED
-> CommitState remains COMMITTED
-> no CREATE retry and no evidence recreation
```

This is different from P8-S79. A deterministic, correctly bound negative
observation is `FAILED`; a timeout, dependency failure, malformed response, or
binding ambiguity is `UNKNOWN`.

## Source Audit

The admitted NSL v0.2 `PostWriteVerifier` already implements the required
state separation. An unmatched but correctly bound `VerificationObservation`
becomes `VerificationStatus.FAILED`, while `VerificationResult.commit_state`
is required to remain `COMMITTED`.

`NslControlledWriteIntegration` dispatches WRITE once and then invokes
post-WRITE verification only for a committed outcome. It has no CREATE retry
path after verification. The production EOS verification adapter also remains
read-only. No production API, database table, migration, or runtime contract
change was required.

## Fault Injection

`scripts/smoke/p8_reliability_faults.py` now provides
`EosVerificationMismatchFaultPort`. It:

1. invokes the real verification delegate exactly once;
2. requires an exact, healthy and positively matched baseline observation;
3. preserves the original request hash, Voucher reference, and observation
   time;
4. changes only `matched` to false and records
   `EOS_VOUCHER_VERIFICATION_DETERMINISTIC_MISMATCH`;
5. is one-shot and fails closed for an unhealthy or unbound baseline.

This prevents the fault harness from manufacturing `FAILED` without first
proving that the committed Voucher is readable through the real EOS endpoint.

## Protected Evidence

The protected scenario used:

```text
nex_ae_test PostgreSQL
nex_wc_test PostgreSQL
nex_oa_test PostgreSQL
nex_eos_test PostgreSQL
admitted NSL v0.2 wheel
NSL v0.2 source-backed Golden A 1.1.0 contract
rustfs/rustfs:1.0.1@sha256:1803faef57627e2d9c2e7d89d655d712ddded5389040054987163043fecb6a3c
SSE-S3 enabled
```

It uploaded and locked three immutable evidence objects, obtained the WC
approval bound to the manifest, committed the attachment-bearing Voucher once,
performed one real EOS verification read, and then injected the deterministic
mismatch.

```text
WRITE dispatch attempts             = 1
authoritative verification reads    = 1
baseline observation matched        = true
injected observation matched        = false
business CommitState                = COMMITTED
verification CommitState            = COMMITTED
VerificationStatus                  = FAILED
eos_business_operation rows         = 1
eos_voucher_draft rows              = 1
eos_voucher_draft_attachment rows   = 3
eos_outbox rows                     = 1
AE attachment batches               = 1
AE attachment rows                  = 3
WC approval work items              = 1
WC approval decisions               = 1
manifest/attachment/object drift    = 0
RustFS object versions per key      = 1
test DB/object residue              = 0
```

Protected result:

```text
1 passed
0 skipped
```

Remote generation, embedding, and reranking providers were not required.

## Regression and Quality Gate

Focused WRITE, reconciliation, verification, and reliability regression:

```text
237 passed
11 protected opt-in skipped
```

The new and reused reliability fault module has:

```text
statement coverage = 100.00%
branch coverage    = 100.00%
```

The NeX-AE Slice Gate completed with:

```text
pytest              = 5,307 passed / 42 protected opt-in skipped
statement coverage  = 98.32% / required 95.00%
branch coverage     = 96.29% / required 94.00%
changed scope       = 100.00% statement / 100.00% branch
contract validation = 191 schemas / 253 positive / 221 negative / 9 OpenAPI
gate exit            = 0
```

The S78 protected scenario has separate zero-skip evidence above.

## Exit Decision

P8-S78 is closed. A committed Voucher and its immutable attachment lineage are
not recreated or rolled back when deterministic post-WRITE verification
fails. P8-S79 may now prove the corresponding `VerificationStatus.UNKNOWN`
boundary for timeout or unavailable verification dependencies.
