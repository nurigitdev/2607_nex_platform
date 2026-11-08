# P8-S86: Full Reliability Protected Gate

## Status

Completed on 2026-10-24.

## Scope

P8-S86 closes P8.8 by running every reliability fault variant from P8-S76
through P8-S86 against actual service databases. It adds one complete
attachment-bearing protected journey that crosses the existing boundaries:

```text
AE immutable attachments and locked manifest
→ WC approval with current OA authority
→ one EOS Voucher WRITE
→ injected commit-acknowledgement loss
→ authoritative EOS reconciliation
→ actual NSL post-WRITE verification
→ cleanup and zero-residue proof
```

The implementation adds only a protected acceptance test and an admitted-wheel
worker. No production source, public API, event contract, database table,
migration, or runtime ordering changed. Remote generation, embedding, and
reranking providers are not required.

## Reliability Contract

The S86 worker enforces these transitions and invariants:

```text
WRITE dispatch count                       = 1
discarded accepted EOS response            = HTTP 201
initial observed state                     = UNKNOWN_COMMIT_STATE
reconciliation result                      = COMMITTED
post-WRITE verification                    = VERIFIED / COMMITTED
BusinessOperationId / IdempotencyKey       = unchanged
PayloadHash / attachment manifest hash     = unchanged
attachment IDs / opaque object references  = unchanged
```

The worker does not replay the WRITE after the ambiguous response. It uses the
existing EOS reconciliation read model and then verifies the reconciled result.

## Protected Evidence

The full protected matrix used actual:

```text
nex_ae_test PostgreSQL as nex_ae_user
nex_wc_test PostgreSQL as nex_wc_user
nex_oa_test PostgreSQL as nex_oa_user
nex_eos_test PostgreSQL as nex_eos_user
rustfs/rustfs@sha256:1803faef57627e2d9c2e7d89d655d712ddded5389040054987163043fecb6a3c
SSE-S3 enabled
admitted nex-skill-language 0.2.0 wheel
```

All P8-S76 through P8-S86 protected tests were selected explicitly with their
guards enabled:

```text
protected fault tests              = 13 passed / 0 skipped
complete S86 journeys              = 1
WRITE dispatches in S86 journey    = 1
Voucher drafts                     = 1
Voucher lines                      = 2
Voucher attachment associations    = 3
BusinessOperations                 = 1
idempotency rows                   = 1
outbox events                      = 1
RustFS versions per attachment     = 1
post-cleanup DB residue            = 0
post-cleanup object residue        = 0
```

The matrix covered ambiguous commit, all reconciliation outcomes,
deterministic and unknown verification failures, outbox and approval ACK loss,
worker crashes after checkpoint and WRITE_REQUESTED, trust revocation, tamper,
cross-tenant isolation, and the complete successful recovery journey.

## Regression And Quality Gates

```text
ruff                                    = PASS
focused reliability regression         = 93 passed / 1 protected skip
P8 regression                           = 1,774 passed / 63 protected skips
full protected reliability matrix       = 13 passed / 0 skipped
NeX-AE Slice Gate                       = 5,355 passed / 45 protected skips
statement coverage                      = 98.32% / required 95.00%
branch coverage                         = 96.28% / required 94.00%
contract validation                     = 191 schemas / 253 positive
                                          / 221 negative / 9 OpenAPI
gate commands                           = 3 / 3
gate exit                               = 0
```

Coverage remained at 32,399 of 32,954 statements and 10,412 of 10,814
branches. The generated coverage report is
`reports/quality/p8-s86-slice.coverage.json`.

The pre-S86 repository Checkpoint Gate also passed with 16,504 tests, 109
protected skips, 98.67% statement coverage, and 97.15% branch coverage.

## Exit Decision

P8-S86 and P8.8 are closed. The reliability model now has deterministic unit
coverage, individual protected fault evidence, and one complete
attachment-bearing recovery journey over actual PostgreSQL and RustFS with no
duplicate business/object mutation and zero cleanup residue. P8-S87 may begin
the P8.9 final gate sequence.
