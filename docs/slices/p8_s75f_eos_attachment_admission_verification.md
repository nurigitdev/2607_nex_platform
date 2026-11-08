# P8-S75F: EOS Attachment Admission and Verification Hardening

## Status

Completed on 2026-10-23.

## Design Decision

P8-S75F preserves attachment bytes in AE-owned immutable RustFS storage and
stores only approved lineage and attachment metadata in EOS.

The EOS Voucher Draft now persists the optional pair:

- `attachment_batch_id`;
- `attachment_manifest_hash`.

Migration `2513_eos_voucher_attachment_lineage` adds these columns and a
fail-closed pair/hash constraint. No attachment byte, bucket, object key,
credential or presigned URL is persisted in EOS.

An attachment-bearing Voucher command must contain both fields. Commands with
no attachments remain backward compatible and persist a null lineage pair.

## Runtime Boundary

EOS resolves every opaque attachment `object_ref` through the authenticated
AE internal endpoint before mutation. The resolver response is a closed
contract and binds:

- tenant, purpose and storage owner;
- attachment, batch and manifest identities;
- immutable object version, content hash, size and media type;
- READY, authenticated and immutable state.

The command projection and AE resolver record must match exactly. A tenant,
object, attachment, batch, manifest, digest, size or media-type substitution
fails before the Voucher transaction commits.

The Voucher Draft, lines, attachment metadata, BusinessOperation,
idempotency record and outbox event remain one EOS database transaction.
Exact command replay returns the existing committed result without resolving
or inserting the attachment a second time.

## Read Models

EOS verification and reconciliation now project:

- `attachment_batch_id`;
- `attachment_manifest_hash`;
- canonical sorted `attachment_ids`.

AE post-write verification and reconciliation require the same closed shape.
Empty Vouchers require an exact null/null/empty lineage. Attachment-bearing
Vouchers require valid UUIDs, a SHA-256 hash reference and sorted unique IDs.
Incomplete, malformed, duplicate or reordered identities fail closed.

## Protected Integration Evidence

The opt-in P8-S75F smoke ran with zero skip against:

- actual `nex_ae_test` as `nex_ae_user`;
- actual `nex_wc_test` as `nex_wc_user`;
- actual `nex_oa_test` as `nex_oa_user`;
- actual `nex_eos_test` as `nex_eos_user`;
- digest-pinned RustFS `1.0.1`.

The smoke performed all service migrations, stored one immutable RustFS
receipt, locked its AE manifest, obtained an OA-authorized WC `NSL_WRITE`
decision, and committed the exact manifest through EOS. It then verified:

- create `201` and exact replay `200`;
- one Voucher, one attachment and one BusinessOperation;
- exact batch, manifest and attachment identity in post-write verification;
- manifest substitution rejection before a second mutation;
- tenant-scoped cleanup in all four databases;
- deletion of the smoke RustFS object.

Result: `1 passed`, `0 skipped`.

Remote embedding, reranking and generation providers were not used or
required for this attachment boundary.

## Regression and Coverage

- Focused EOS/AE attachment regression: `170 passed`, with two unrelated
  protected tests skipped by their own opt-in flags.
- S60/S61 lineage regression: `126 passed`; both modified adapter modules
  reached `100%` statement and branch coverage.
- NeX-EOS Slice Gate: `593 passed`, `18` protected skips; statement `99.13%`,
  branch `98.48%`.
- NeX-AE Slice Gate: `5,276 passed`, `42` protected skips; statement `98.31%`,
  branch `96.28%`.
- Contract validation: `191` schemas, `253` examples, `221` negative examples
  and `9` OpenAPI documents passed.

The AE branch coverage is unchanged from the P8-S75E baseline.

## Exit Decision

P8-S75F is closed. No attachment substitution, omission or cross-tenant
association can produce a committed Voucher through the admitted path.
P8-S75G may now expose the locked manifest and protected attachment gateway in
the authenticated IA experience without changing the backend persistence
contract.
