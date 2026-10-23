# P8-S75E: Canonical AttachmentManifest and Approval Binding

## Status

Completed on 2026-10-23.

## Design Decision

P8-S75E uses the existing AE attachment columns reserved in P8-S75B. No new
table or migration was required.

The canonical manifest contains the owner-scoped batch identity and a sorted
projection of each active attachment:

- `attachment_id`;
- opaque `object_ref` and optional object version;
- display name and media type;
- byte size and content SHA-256;
- optional evidence reference.

Items are sorted by `attachment_id` before hashing. The manifest hash is a
shared `semantic_sha256_hash_ref`, and its exact allowed fields are closed.
Reordering therefore preserves identity while a rename, replacement, content
digest or object-reference change creates a new identity.

## Durable Lock

`SqlAlchemyVoucherAttachmentRepository.lock_manifest()` performs one database
transaction that:

1. locks and validates a `READY` batch;
2. builds the deterministic manifest;
3. persists `attachment_manifest_hash` and `locked_at`;
4. moves the batch and every active item to `LOCKED`;
5. rebuilds and verifies the persisted manifest before commit.

An exact replay returns the same manifest. Upload, removal, replacement and
metadata mutation after lock fail closed. A persisted row change is detected
as manifest-integrity failure.

The owner-authenticated `/lock` operation is the admission point used before
approval publication. It does not expose RustFS location or credentials.

## Approval Lineage

- WorkIntent receives one `ATTACHMENT_MANIFEST` constraint containing batch
  ID, manifest hash, attachment count and byte total.
- The deterministic PLAN binder carries the same identity into the
  `LOCAL_SKILL` ExecutablePlan as a literal input binding.
- The governed Voucher payload includes `attachment_batch_id`,
  `attachment_manifest_hash` and the exact sorted EOS attachment projection.
- The NSL payload hash therefore changes for every material manifest change.
- ApprovalRequest display-safe metadata binds the same manifest identity.
- Existing Platform ApprovalEvidence remains schema-compatible: its exact
  ApprovalRequest ID, payload hash and write-intent hash prove the attachment
  lineage transitively.
- A stale ApprovalRequest or Platform ApprovalEvidence cannot authorize a
  changed manifest.

The EOS parser and resolver admission for the two new governed payload fields
is intentionally completed in P8-S75F.

## Verification

- Focused manifest/planning/API regression: `39 passed`.
- New manifest module statement/branch coverage: `99%`.
- Determinism, reorder, rename, object substitution, malformed shape,
  duplicate binding, stale request/evidence, lock replay and post-lock
  mutation cases passed.
- Actual protected smoke: `1 passed` against the actual `nex_ae_test`
  PostgreSQL database and digest-pinned RustFS `1.0.1`.
- The protected smoke verified migration presence, immutable object publish,
  finalize, lock, replay, protected read, late upload/removal denial, database
  hash/state and zero-residue cleanup.
- AE Slice Gate: `5,259 passed`, `42 skipped` protected tests, statement
  coverage `98.31%`, branch coverage `96.28%`, and contract validation passed
  for `191` schemas, `253` examples, `220` negative examples and `9` OpenAPI
  documents.

The S75E protected test is explicitly enabled and cannot report success by
silently skipping PostgreSQL or RustFS operations.

## Exit Decision

P8-S75E is closed. P8-S75F may now admit the exact manifest-bound payload at
EOS, authenticate object resolution, preserve atomic Voucher attachment
commit and verify the same identities during post-write verification and
reconciliation.
