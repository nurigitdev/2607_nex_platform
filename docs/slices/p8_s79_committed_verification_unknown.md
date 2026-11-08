# P8-S79: COMMITTED + Verification UNKNOWN

## Status

Completed on 2026-10-24. P8-S80 is next.

## Boundary

P8-S79 proves that an unavailable or timed-out post-WRITE verification result
does not change or recreate an already committed business outcome:

```text
one EOS CREATE dispatch
-> Voucher + attachment associations + outbox COMMITTED
-> one healthy authoritative EOS read-back
-> verification response discarded as TimeoutError
-> VerificationStatus UNKNOWN / VERIFICATION_TIMEOUT
-> CommitState remains COMMITTED
-> no CREATE, upload, association, or manifest retry
```

`UNKNOWN` is not `FAILED`. S78 used a correctly bound deterministic negative
observation and therefore produced `FAILED`. S79 deliberately makes the read
outcome unavailable, so the verifier cannot assert either match or mismatch.

## Source Audit

The admitted NSL v0.2 `PostWriteVerifier` already implements the required
state separation:

```text
TimeoutError                    -> UNKNOWN / VERIFICATION_TIMEOUT
other dependency exception     -> UNKNOWN / VERIFICATION_DEPENDENCY_FAILURE
malformed observation          -> UNKNOWN / VERIFICATION_RESPONSE_MALFORMED
binding mismatch               -> UNKNOWN / VERIFICATION_BINDING_MISMATCH
```

Every result retains `CommitState.COMMITTED`. `NslControlledWriteIntegration`
dispatches WRITE once before verification and has no CREATE retry path after
an unknown verification result. No production API, table, migration, or
runtime contract change was required.

## Fault Injection

`scripts/smoke/p8_reliability_faults.py` now provides
`EosVerificationTimeoutFaultPort`. It:

1. invokes the actual EOS verification delegate exactly once;
2. requires a healthy observation bound to the exact request hash and Voucher
   reference;
3. records that healthy baseline before discarding the response;
4. raises `TimeoutError` once so admitted NSL maps it to
   `VERIFICATION_TIMEOUT`;
5. rejects repeat injection and unhealthy or unbound baselines.

The existing S78 verification worker now supports both deterministic mismatch
and timeout modes. This keeps request construction, admitted wheel loading,
actual WRITE dispatch, and result projection on one shared execution path.

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

It uploaded and locked three immutable evidence objects, obtained WC approval
bound to that manifest, committed one attachment-bearing Voucher, confirmed a
healthy EOS verification response, and then discarded the response as a
timeout.

```text
WRITE dispatch attempts             = 1
authoritative verification reads    = 1
baseline observation matched        = true
injected failure                    = TimeoutError
business CommitState                = COMMITTED
verification CommitState            = COMMITTED
VerificationStatus                  = UNKNOWN
verification reason                 = VERIFICATION_TIMEOUT
verification evidence ref           = null
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
245 passed
12 protected opt-in skipped
```

The shared reliability fault module retained:

```text
statement coverage = 100.00%
branch coverage    = 100.00%
```

The NeX-AE Slice Gate completed with:

```text
pytest              = 5,315 passed / 42 protected opt-in skipped
statement coverage  = 98.32% / required 95.00%
branch coverage     = 96.29% / required 94.00%
changed scope       = 100.00% statement / 100.00% branch
contract validation = 191 schemas / 253 positive / 221 negative / 9 OpenAPI
gate exit            = 0
```

The S79 protected scenario has separate zero-skip evidence above.

## Exit Decision

P8-S79 is closed. A timed-out or otherwise unavailable verification result is
not interpreted as a failed commit and cannot cause WRITE or attachment
recreation. P8-S80 may now isolate outbox publication acknowledgement loss so
only event publication is retried while the business mutation count remains
one.
