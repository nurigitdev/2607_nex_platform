# P8-S85: Tamper / Cross-Tenant Matrix

## Status

Completed on 2026-10-24.

## Scope

P8-S85 closes the canonical tamper and cross-tenant attack matrix without
introducing a second authorization, storage, or transaction mechanism. The
source audit assigned every attack to its existing authoritative boundary:

| Attack | Authoritative rejection boundary |
|---|---|
| ApprovalEvidence tamper | AE evidence integrity validation |
| PayloadHash mismatch | EOS canonical payload admission |
| WriteIntentHash mismatch | AE approved-manifest binding |
| cross-tenant Project | EOS tenant-scoped Project lookup |
| cross-tenant Account | EOS tenant-scoped Account lookup |
| cross-tenant attachment | authenticated AE-to-EOS attachment resolution |
| stale Claim delegation | WC current parent Claim/Assignment authority |
| manifest drift | EOS immutable manifest lineage |
| attachment substitution | EOS attachment identity lineage |
| object_ref tenant isolation | AE-owned opaque reference resolution |

No production source, public API, event schema, table, migration, or runtime
ordering changed. The implementation is a focused regression and protected
acceptance closure over the existing boundaries.

## Zero-Mutation Contract

Each rejected EOS command uses a fresh BusinessOperationId and IdempotencyKey.
After every attack, the test asserts that both the requesting and foreign
tenant retain zero rows in:

```text
eos_business_operation
eos_idempotency
eos_voucher_draft
eos_voucher_draft_line
eos_voucher_draft_attachment
eos_outbox
```

The stale Claim case preserves the exact WC baseline and creates neither a
child WorkItem nor delegation lineage. ApprovalEvidence integrity failure
creates no idempotency or WRITE_REQUESTED evidence. WriteIntentHash drift is
rejected before the WRITE boundary.

## Protected Evidence

The opt-in protected suite used actual:

```text
nex_ae_test PostgreSQL as nex_ae_user
nex_wc_test PostgreSQL as nex_wc_user
nex_oa_test PostgreSQL as nex_oa_user
nex_eos_test PostgreSQL as nex_eos_user
rustfs/rustfs@sha256:1803faef57627e2d9c2e7d89d655d712ddded5389040054987163043fecb6a3c
SSE-S3 enabled
```

It created one primary attachment, one same-tenant substitution candidate,
and one foreign-tenant attachment. All six EOS attack commands were rejected;
the direct foreign-object resolution was 404, all three RustFS object-version
identities were unchanged after every attack, and cleanup left zero database
and object residue.

Observed result:

```text
protected tests                    = 3 passed / 0 skipped
canonical attack rows              = 10
EOS unauthorized mutation rows     = 0
WC stale-child mutation rows       = 0
AE downstream WRITE rows           = 0
RustFS object-version drift        = 0
test DB/object residue             = 0
```

Remote generation, embedding, and reranking providers were not required.

## Verification

```text
focused S85 regression             = 12 passed
related boundary regression        = 79 passed / 5 protected skips
P8 regression                      = 1,774 passed / 62 protected skips
NeX-AE Slice Gate                  = 5,367 passed / 47 protected skips
statement coverage                 = 98.32% / required 95.00%
branch coverage                    = 96.28% / required 94.00%
contract validation                = 191 schemas / 253 positive
                                     / 221 negative / 9 OpenAPI
gate commands                      = 3 / 3
gate exit                          = 0
```

Coverage raw counts are unchanged from P8-S84: 32,399 of 32,954 statements
and 10,412 of 10,814 branches. The generated report is
`reports/quality/p8-s85-slice.coverage.json`.

## Exit Decision

P8-S85 is closed. Tampered approval and WRITE lineage, canonical payload
drift, cross-tenant business references, attachment substitution, opaque
object-reference isolation, and stale delegation authority all fail closed at
their owning boundary with zero unauthorized mutation. P8-S86 may now run the
full reliability protected gate.
