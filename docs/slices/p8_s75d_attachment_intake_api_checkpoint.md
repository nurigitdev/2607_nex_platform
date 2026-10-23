# P8-S75D: AE Multiple-File Intake API and Batch Lifecycle

## Status

Completed on 2026-10-23.

## Scope

P8-S75D exposes an authenticated Voucher evidence intake boundary over the
durable AE metadata and immutable RustFS object gateway completed in P8-S75B
and P8-S75C.

- Voucher evidence uses dedicated `/api/v1/voucher-attachments` routes and
  does not create or reuse the CX document-ingestion workflow.
- A browser owner creates one batch and uploads each file independently, so a
  failed file can be retried without loading or replaying the entire batch.
- Batch reads expose safe item state, byte totals and progress metadata.
- An owner may remove an item before lock; metadata becomes `REMOVED` and its
  unreferenced object is deleted through the AE-owned object gateway.
- Finalization accepts zero-file batches and batches whose active items are
  all `READY`. Partial, failed or quarantined content fails closed.
- Exact item replay returns the existing immutable object and identity.

## Protected Content Access

- The authenticated owner may preview or download a `READY` or `LOCKED` item.
- Only authenticated `nex-wc` and `nex-eos` service principals may use the
  reviewer/service path. Other services fail with `403`.
- The API streams a bounded, digest- and size-verified spool with private,
  no-store response headers.
- Bucket names, object keys, credentials, filesystem paths and presigned URLs
  are never returned to the caller.
- A session expiry, tenant mismatch, owner mismatch, missing item or storage
  integrity failure is rejected before content is returned.

## Verification

- Focused S75D API regression: `9 passed`.
- Combined attachment/object-storage focused regression: `71 passed`.
- Changed-module coverage: statement and branch coverage `94%` combined;
  `voucher_attachment_api.py` reached `98%` statement coverage.
- Actual protected API smoke: `1 passed` against the actual `nex_ae_test`
  PostgreSQL database and digest-pinned RustFS `1.0.1`.
- The live smoke executed migration verification, authenticated batch create,
  multipart upload, duplicate replay, protected preview, finalize, pre-lock
  removal, PostgreSQL cleanup and RustFS object cleanup.
- Remote embedding, reranking and generation providers were not required.

## P8.7A Checkpoint Gate

The mandatory gate after P8-S75D passed:

- statement coverage: `98.70%` (threshold `95.00%`);
- branch coverage: `97.19%` (threshold `94.00%`);
- contract validation: `191` schemas, `253` examples, `220` negative
  examples and `9` OpenAPI documents;
- checkpoint commands: `3/3` passed in `895.852s`.

Local machine-readable evidence is written to
`reports/quality/checkpoint-latest.json` and
`reports/quality/checkpoint.coverage.json`.

## Exit Decision

P8-S75D and the P8.7A Checkpoint Gate are closed. P8-S75E may now construct a
deterministic canonical attachment manifest, lock it before approval
publication and bind its identity to the governed approval lineage.
