# P8-S65A: Golden A Canonical Write Payload and Approval Hash Alignment

## Status

Completed on 2026-10-23.

## Decision

Golden A uses one NSL-compatible canonical business payload from Skill
execution through EOS commit. The payload contains stable ProjectRef and
AccountRef values, deterministic voucher metadata, and balanced debit and
credit lines. It does not contain approval workflow identities.

The canonical separation is:

```text
business payload
  schema_version, tenant_id, requester_ref, project_ref
  voucher_type, transaction_date, currency, description_text
  balanced lines, attachments

control lineage
  approval_request_id
  approval_evidence_ref
  business_approval_proof_ref
  business_operation_id, idempotency_key, trace
```

`nsl_approval_request_id`, `nsl_approval_evidence_ref`, and
`business_approval_proof_ref` are injected by the admitted AE write adapter
after payload-hash verification. Changing those control values cannot change
the business payload hash.

The NSL Tool contract uses `description_text` because `description` is reserved
by the NSL DSL. AE maps it to the existing EOS public command field
`description`; EOS reconstructs `description_text` only for canonical hash
verification. No EOS public API field or database schema changed.

## NSL Contract Baseline

The source-backed Golden A Skill and tool contract were versioned together:

```text
Skill              = FINANCE.VOUCHER_DRAFT_CREATE @ 1.1.0
WRITE tool         = FINANCE.CREATE_VOUCHER_DRAFT @ 1.1.0
Skill semantic hash= sha256:b6ba60f6ae681dc754b6d304fcf7c99794a48e88429c698afd9d12afcb90a8fc
NSL source commit  = c0a8d4e125ee129c4556d896356237bb3973582d
NSL source tree    = 057611c8c584afa5483f7f3e5990a19533ddea58
```

The admitted wheel bytes did not change, so its digest remains:

```text
sha256:862958a5eab982a71bec5ee58b9e530867d6c25f65d8b770efb29ca78ce7f135
```

The Platform source lock and package admission constants now identify the new
source commit/tree while retaining that wheel digest. S63 and S64 fixtures bind
the exact Skill version and semantic hash.

The v1.1 WRITE contract also names `FINANCE.GET_VOUCHER_DRAFT` as its
post-WRITE verification tool. This matches the Platform EOS adapter's canonical
read-back operation ID; the earlier source-only `FINANCE.GET_VOUCHER` alias was
removed before P8-S66 admission.

## Hash Continuity

The protected Golden A journey produced this canonical runtime payload hash:

```text
sha256:240a7e83a1b3355ba98b5473cc239f1aea6a318b17e53e385c01837666fb8eb9
```

The hash was computed from the NSL Tool-contract payload and matched the
persisted ApprovalRequest. P8-S66 must read and pass this same value through
`WriteCallRequest` to EOS; it must not recompute the hash from the EOS wire
command after approval lineage has been added.

The generic static EOS contract example has its own example-specific payload
hash, `sha256:1705802a128eb6206a7e8f9547bb4074d3699c27a6e87ad69b3b6a0def4c02ba`.
That value is not the S65 Golden A runtime hash and must not be used by S66.

## Protected Evidence

The S65 journey was rerun against actual `nex_ae_test`, `nex_wc_test`, and
`nex_oa_test` PostgreSQL databases and the live generation provider. All
migrations were current, the admitted Skill was exactly version `1.1.0`, and
the live INTENT then PLAN stages used `Qwen3.5-4B`.

```text
checks                    = 20/20 PASS
actual PostgreSQL         = true
actual generation provider= true
approval                  = APPROVED
resume                    = DONE
canonical hash preserved  = true
EOS mutations             = 0
AE/OA/WC cleanup          = complete
```

Sanitized machine evidence is stored at
`/tmp/nex-p8-s65a-golden-a-live.json`. Secrets, raw prompts, model output, and
tenant-private payloads are excluded.

## Verification

- NSL focused Golden A tests: `2 passed`.
- NSL full regression: `2,309 passed`; total coverage `98.95%`.
- Platform changed-surface regression: `246 passed`, `6 skipped` protected
  tests.
- NeX-AE Slice Gate: `5,130 passed`, `35 skipped`; statement `98.41%`, branch
  `96.38%`.
- NeX-EOS Slice Gate: `379 passed`, `13 skipped`; statement `99.80%`, branch
  `100.00%`.
- Contract validation: 188 schemas, 250 positive examples, 217 negative
  examples, and 9 OpenAPI documents.

## Exit Decision

P8-S65A is closed. Golden A has one model-independent canonical business
payload and one payload hash across NSL admission, human approval, AE write
adaptation, EOS commit, and read-back verification. Approval metadata remains
independently auditable control lineage. P8-S66 confirmed the same approved
hash through an actual `COMMITTED` and `VERIFIED` journey.
