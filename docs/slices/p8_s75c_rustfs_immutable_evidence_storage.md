# P8-S75C: RustFS Immutable Evidence Storage and Resolver

## Status

Completed on 2026-10-23.

## Scope

P8-S75C connects the durable AE attachment metadata from P8-S75B to the
existing S3-compatible private object-storage boundary used with RustFS.

- `S3ObjectStore.put_immutable_stream()` validates a seekable stream in fixed
  chunks and publishes it without converting the complete file to a byte
  array.
- `VoucherAttachmentObjectGateway` spools each file with a 1 MiB memory
  threshold and enforces the frozen 25 MiB per-file limit.
- Object keys are derived from tenant, owner and attachment identities but
  remain private to AE. Public references use a deterministic opaque
  `objref:ae:voucher:*` identity.
- AE persists only digest, size, media type, opaque object/version references,
  scan admission and evidence metadata.
- The EOS-purpose resolver requires authenticated `nex-eos` authority and
  validates tenant, purpose, state, scan admission, digest, size, media type,
  encryption and object version before returning a safe resolution.

No RustFS-specific SDK was introduced. RustFS remains behind the shared
S3-compatible port.

## Lifecycle and Safety

- Publication is immutable and exactly replayable for the same object.
- A conflicting object at the deterministic key fails with `409`.
- Raw bucket names, object keys, credentials, endpoints and presigned URLs are
  excluded from the resolver projection.
- Owner reads revalidate PostgreSQL metadata against the stored object.
- Cross-tenant, wrong-owner, unauthenticated service and wrong-purpose access
  fail closed.
- Cleanup may delete only an unreferenced object associated with an
  unpublished item. `READY` or `LOCKED` objects cannot be removed by this
  cleanup path.
- External malware scanning remains a pluggable later policy. This Slice marks
  only content that passed the current bounded stream, media, hash and object
  admission boundary as `CLEAN`.

## Verification

- Focused S75B/S75C object-storage regression: `62 passed`.
- Changed-module statement/branch coverage: `96%` combined;
  `voucher_attachment_storage.py` is `99%`,
  `voucher_attachments.py` is `96%`, and shared `object_storage.py` is `95%`.
- Actual protected smoke: `1 passed` against digest-pinned RustFS `1.0.1` and
  the actual `nex_ae_test` PostgreSQL database.
- The live smoke verified bucket versioning/encryption/lifecycle bootstrap,
  immutable put/head, PostgreSQL publication, authenticated EOS-purpose
  resolution, owner read, database cleanup, object delete and missing head.
- The protected test requires explicit enablement and therefore cannot pass by
  silently skipping the RustFS or PostgreSQL operations.
- Remote embedding, reranking and generation providers were not required.

## Exit Decision

P8-S75C is closed. P8-S75D may expose authenticated batch intake,
independently retryable file upload, progress, pre-lock removal and protected
preview/download APIs over this storage gateway.
