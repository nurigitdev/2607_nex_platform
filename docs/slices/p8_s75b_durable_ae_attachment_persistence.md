# P8-S75B: Durable AE Attachment Persistence

## Status

Completed on 2026-10-23.

## Scope

P8-S75B adds the AE-owned durable metadata boundary for Voucher evidence
attachment batches and items. It introduces:

- `ae_voucher_attach_batch` for owner, Conversation, Interaction, trace,
  aggregate size/count and immutable-manifest lifecycle state;
- `ae_voucher_attachment` for stable item identity, display metadata, content
  digest, opaque object/version references, scan state and evidence reference;
- `SqlAlchemyVoucherAttachmentRepository` with exact replay, semantic conflict,
  atomic batch-limit enforcement and restart-safe reads.

The tables contain metadata only. Raw bytes, filesystem paths, S3 URLs,
presigned URLs and storage credentials are excluded.

## Persistence Decisions

- Primary scope is `(tenant_id, attachment_batch_id)`.
- A Conversation Interaction may create at most one attachment batch per
  tenant.
- Batch and item identifiers are caller-assigned UUIDs and support exact
  replay.
- Registration locks the batch row on PostgreSQL before enforcing the maximum
  count and aggregate byte limit.
- A locked or abandoned batch cannot accept new items.
- Database errors are converted to redacted, typed persistence errors.
- Binary publication and immutable object references remain P8-S75C scope.

## Verification

- Focused persistence coverage: `29 passed`; new module statement/branch
  coverage `99%` under SQLite. The remaining branch is PostgreSQL-only row
  locking and is exercised by the protected smoke.
- S75A/S75B and existing AE upload/migration regression: `121 passed`.
- Actual `nex_ae_test` migration/state smoke: `1 passed`, with migration
  `2513_ae_voucher_attachment` confirmed in `schema_migrations`.
- The protected PostgreSQL test performs create, exact replay, item register,
  repository restart/read, direct row-count verification and cleanup. It is
  not skipped when `NEX_AE_P8_S75B_POSTGRES_SMOKE=1` is supplied.
- RustFS and remote model providers were not required for this Slice.

## Exit Decision

P8-S75B is closed. P8-S75C may add bounded binary ingestion and immutable
RustFS publication while reusing these metadata tables and ownership rules.
