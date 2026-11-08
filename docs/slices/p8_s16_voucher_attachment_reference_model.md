# P8-S16: Voucher Attachment Metadata and Object Reference Model

Completed on 2026-10-21. NeX-EOS now owns Voucher attachment associations and
bounded metadata while binary content remains in owner-managed object storage.

## Scope

- Added migration `2507_eos_voucher_attachment` and table
  `eos_voucher_draft_attachment`.
- Added optional 0/1/N attachment association with stable attachment identity,
  opaque `object_ref`, copied content metadata, evidence ref, and immutable
  object version ref.
- Added an injected authoritative resolver protocol instead of a RustFS SDK or
  caller-constructed bucket/key parser.
- Required a fresh authenticated resolver result proving exact tenant,
  `EOS_VOUCHER_ATTACHMENT` purpose, `READY` state, immutable object state, and
  exact hash/size/media metadata.
- Rejected URLs, storage paths, credential-like references, resolver failure,
  cross-tenant results, wrong purpose, deleted/quarantined state, mutable
  objects, and metadata mismatch before association persistence.

EOS does not persist object bytes, RustFS credentials, presigned URLs, bucket
names, object keys, or filesystem paths. An empty attachment set returns
without invoking the resolver or object storage. Therefore the optional Golden
A path does not require live RustFS; a future live attachment scenario must
provide a real authenticated owner resolver and RustFS-backed integrity
evidence.

## Verification

- Focused attachment regression: 28 passed.
- `attachments.py` statement coverage: 100%; branch coverage: 100%.
- Actual dev/test PostgreSQL migrations applied `2507`.
- Protected PostgreSQL smoke connected as `nex_eos_user@nex_eos_test`, created
  a Voucher and resolver-validated attachment association, reread copied
  metadata, and left zero residue.
- EOS Slice Gate: 211 passed, 9 protected skips.
- EOS statement coverage: 99.70%; branch coverage: 100%.
- Repository Full Gate: 15,771 passed, 57 protected skips in 1,885.68 seconds.
- Full Gate statement coverage: 96.86% (`159,809 / 164,988`).
- Full Gate branch coverage: 96.26% (`35,555 / 36,936`).
- Contract validation: 174 schemas, 236 examples, 204 negative examples, and
  9 OpenAPI documents.
- Remote model providers were not required.
