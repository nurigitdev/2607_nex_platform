# P8-S75A: Source-Backed Attachment Contract Closure

## Status

Completed on 2026-10-23.

## Scope

P8-S75A audited the existing AE upload, shared S3-compatible object storage and
EOS Voucher attachment boundaries before introducing persistence or runtime
behavior. It freezes three additive machine-readable contracts:

- `ae_voucher_attachment_batch.v1` for owner-scoped intake lifecycle;
- `ae_voucher_attachment_manifest.v1` for the immutable approval binding;
- `ae_voucher_attachment_resolution.v1` for authenticated EOS object
  resolution.

The existing CX document upload remains separate and is not reused as an
implicit Voucher evidence ingestion path.

## Frozen Initial Policy

```text
maximum attachment count: 20
maximum file size:         25 MiB
maximum batch size:        100 MiB
binary owner:              RustFS through AE-owned object storage
intake/manifest owner:     AE
human decision owner:      WC
decision authority owner:  OA
Voucher association owner: EOS
```

The initial media policy admits PDF, JPEG, PNG, WebP, opaque ZIP, OOXML office
documents and HWP media types. ZIP content is not expanded. Raw attachment
content is not sent to NSL, an LLM or CX by this contract.

## Security And Integrity

- Stable contracts contain no bytes, filesystem path, S3 URI, presigned URL or
  storage credential.
- EOS resolution is valid only for the exact tenant, AE storage owner, purpose
  `EOS_VOUCHER_ATTACHMENT`, `READY` state, authenticated result and immutable
  object.
- The locked manifest binds stable object/version identity, display name,
  media type, size and SHA-256.
- The existing EOS command and AE batch both cap attachments at twenty.

## Verification

- Focused S75A contract tests: `10 passed`.
- Contract validation: `191` schemas, `253` examples, `220` negative examples
  and `9` OpenAPI documents.
- No database migration, runtime route or production behavior was changed.
- Remote model providers and RustFS runtime access were not required.

## Exit Decision

P8-S75A is closed. P8-S75B may add the durable AE attachment batch and item
model without changing the frozen ownership, limit or evidence boundaries.
