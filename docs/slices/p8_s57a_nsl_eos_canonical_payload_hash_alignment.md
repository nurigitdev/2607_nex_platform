# P8-S57A: NSL-EOS Canonical Payload Hash Alignment

## Status

Completed on 2026-10-22.

## Reason for the Amendment

P8-S57 source audit found that NSL v0.2 and EOS used different hash domains
for the same canonical WRITE payload:

```text
NSL  = SHA-256("NSL-WRITE-PAYLOAD-V1\0" + canonical arguments)
EOS  = SHA-256(canonical business payload)
```

An adapter could therefore neither forward the NSL `PayloadHash` unchanged nor
recalculate an EOS-only value without violating the frozen approval,
idempotency, and write-evidence lineage. P8-S57A closes that incompatibility
before transport integration.

## Implementation

`nex_runtime.semantic_hashes.nsl_write_payload_hash_ref()` now implements the
frozen NSL v0.2 domain-separated algorithm for canonical JSON WRITE values.
It accepts mappings with string keys and canonical JSON scalar/container
values, normalizes tuples as arrays, and rejects floats, opaque Python objects,
non-string keys, and non-mapping roots.

EOS `voucher_payload_hash()` and the mutation-boundary validation now apply
that helper to `ParsedVoucherDraftCommand.business_payload()`. The existing
generic `semantic_sha256_hash_ref()` remains unchanged for every non-NSL hash
domain.

No database migration, API field, route, or persistence owner changed. EOS
continues to reconstruct the canonical business payload and fails closed
before authorization or mutation when the supplied hash differs.

## Golden Vector

The Golden A Voucher command and committed result now carry the actual shared
payload identity:

```text
sha256:dc50539078c469eedbbd457a25b8036bc4a31cd10d5ab55431475f373d49d76f
```

The protected test loads the admitted NSL v0.2 wheel in a fresh subprocess,
wraps every canonical business field in a real NSL `ValueEnvelope`, invokes
the wheel's `compute_payload_hash()`, and compares it with the Platform helper
and EOS contract example.

Wheel evidence:

- package version: `0.2.0`
- source revision: `a5a0f5fd7acf4adbbccf890dca2f9998d055d65e`
- wheel digest:
  `sha256:862958a5eab982a71bec5ee58b9e530867d6c25f65d8b770efb29ca78ce7f135`
- import origin: admitted wheel under
  `reports/deployment/p8-nsl-v0.2-wheel/`

The host NSL v0.1 installation was not modified.

## Verification

- hash helper and EOS command focused tests: `49 passed`; both changed modules
  reached statement `100%` and branch `100%` coverage.
- actual admitted NSL v0.2 wheel cross-implementation smoke: `1 passed`.
- P8-S54 through P8-S56 plus EOS contract/command regression: `141 passed`.
- NeX-EOS Slice Gate: `342 passed`, `10 protected skips`; statement `99.80%`,
  branch `100%`.
- changed scope coverage: helper `100%/100%`, EOS command `100%/100%`.
- contract validation: 188 schemas, 250 examples, 217 negative examples, and
  9 OpenAPI documents.
- actual `nex_eos_test` protected smoke: `2 passed`; command commit, exact
  replay, operation query, read-only verification, and zero residue confirmed.
- existing hash-mismatch test still proves zero Voucher, BusinessOperation,
  idempotency, and outbox mutation.

## Exit Decision

P8-S57A is closed. P8-S57 may now implement the EOS-backed NSL
`WriteExecutionPort` adapter and must forward the existing `PayloadHash`,
`IdempotencyKey`, and `BusinessOperationId` unchanged. It must not introduce a
second payload hash, embed EOS SQL, or recalculate business identity.
