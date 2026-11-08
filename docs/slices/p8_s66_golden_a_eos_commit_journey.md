# P8-S66: Golden A EOS Commit Journey

## Status

Completed on 2026-10-23.

## Scope

P8-S66 continued the actual P8-S65 approval lineage through the governed NSL
WRITE path:

```text
approved canonical payload
-> WRITE_REQUESTED evidence
-> EOS PostgreSQL transaction
-> Voucher Draft and outbox
-> COMMITTED outcome
-> authoritative read-back verification
```

The Platform host keeps NSL v0.1 installed. The protected runner therefore
installs the admitted NSL v0.2 wheel into a temporary target and executes only
the controlled-WRITE portion in an isolated worker. OA and EOS remain real
local HTTP services backed by their actual PostgreSQL test databases. The host
environment and database schemas were not changed by this isolation boundary.

## Contract Alignment

The live gate found and closed one source-backed contract mismatch before
admission: the Golden A v1.1 contract used `FINANCE.GET_VOUCHER`, while the
canonical Platform EOS read-back adapter uses `FINANCE.GET_VOUCHER_DRAFT`.
The NSL Skill and Tool catalog now use the Platform operation ID consistently.

```text
NSL source commit   = c0a8d4e125ee129c4556d896356237bb3973582d
NSL source tree     = 057611c8c584afa5483f7f3e5990a19533ddea58
Skill               = FINANCE.VOUCHER_DRAFT_CREATE @ 1.1.0
Skill semantic hash = sha256:b6ba60f6ae681dc754b6d304fcf7c99794a48e88429c698afd9d12afcb90a8fc
Verification tool   = FINANCE.GET_VOUCHER_DRAFT @ 1.0.0
```

The wheel contains no changed package code, so its admitted byte digest remains
`sha256:862958a5eab982a71bec5ee58b9e530867d6c25f65d8b770efb29ca78ce7f135`.
The source revision/tree, fixture hash, S63/S64 binding, and admission constants
were refreshed together.

## Hash Continuity

The S65 ApprovalRequest hash was reused without translation:

```text
sha256:240a7e83a1b3355ba98b5473cc239f1aea6a318b17e53e385c01837666fb8eb9
```

The protected gate compared this value at five boundaries: S65 evidence,
worker canonical payload, NSL `WriteCallRequest`, EOS committed outcome, and
post-WRITE verification identity. Approval request and evidence references were
transmitted separately as control lineage and did not affect the business
payload hash.

## Protected Evidence

The gate used actual `nex_ae_test`, `nex_wc_test`, `nex_oa_test`, and
`nex_eos_test` PostgreSQL databases plus the live generation provider. The S65
prerequisite completed with `Qwen3.5-4B`, approval `APPROVED`, and resume state
`DONE` before EOS WRITE execution began.

The commit produced exactly:

```text
BusinessOperation       1
EOS idempotency record  1
Voucher Draft           1
Voucher lines           2
Voucher attachments     0
Outbox event             1
AE idempotency evidence 1
AE WRITE evidence       1
```

The outcome was `COMMITTED`, the authoritative read-back was `VERIFIED`, and
all 12 protected checks passed. Tenant-scoped cleanup then proved zero residue
across AE, OA, and EOS fixture/mutation rows. Sanitized machine evidence is
stored at `/tmp/nex-p8-s66-golden-a-eos-commit.json`; credentials, raw prompts,
model output, and private business payload are excluded.

## Verification

- NSL Golden A focused regression: `2 passed`.
- Platform P8 admission/fixture/planning/approval focused regression:
  `151 passed`, `2 skipped` protected tests.
- P8-S66 focused regression: `37 passed`, `2 skipped` protected tests.
- Protected PostgreSQL/live-provider gate: `PASS`, `12/12` checks.
- Commit state: `COMMITTED`; verification status: `VERIFIED`.
- NeX-AE Slice Gate: `5,135 passed`, `36 skipped`; statement `98.41%`,
  branch `96.38%`.
- NeX-EOS Slice Gate: `379 passed`, `13 skipped`; statement `99.80%`,
  branch `100.00%`.
- Contract validation: 188 schemas, 250 positive examples, 217 negative
  examples, and 9 OpenAPI documents.

## Exit Decision

P8-S66 is closed. Golden A now preserves one approved canonical business
payload hash from human approval through actual EOS commit and authoritative
verification. The next boundary is P8-S67, which must prove exactly-once
business mutation under duplicate delivery, worker retry, and acknowledgement
loss variants.
