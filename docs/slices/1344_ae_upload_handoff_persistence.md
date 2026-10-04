# Slice 1344: AE upload handoff persistence

## Outcome

- Added the bounded `ae_upload_handoffs` table with owner, workspace, CX
  document, source hash, status, and time indexes.
- Added a SQLAlchemy store selected automatically from the AE API persistence
  runtime; `local_mock` retains the in-memory adapter.
- Persisted only handoff metadata. Source bytes, extracted text, Markdown,
  chunks, vectors, credentials, and raw tokens are rejected recursively.
- Applied tenant and owner filters inside upload/document read queries, so a
  cross-owner lookup is existence-hiding `404` rather than an in-memory `403`.
- Hardened historical S133 migration checks to preserve the 89-migration
  baseline while allowing later service-owned migrations.

## Boundary

SQLite regression proves adapter behavior and restart-style readback in this
Slice. Actual `nex_ae_test` migration and protected PostgreSQL journey evidence
remain scheduled for Slice 1350. CX continues to own source and derived private
content.

## Verification

- Focused regression: `107 passed`; persistence-only regression: `9 passed`.
- Slice Gate (`nex-ae-api`): `2814 passed`, `5 skipped`; statement coverage
  `98.34%`, branch coverage `96.23%`; all `5/5` commands passed.
- Changed persistence and evidence statement/branch coverage: `100.00%` /
  `100.00%`.
- Static database audit: `24` AE migrations, `18` core tables, no missing
  repository references, and all new table/index names below PostgreSQL's
  identifier limit.
- Persistence evidence requires nine checks, three bounded indexes, no private
  payload, and `next=1345`.
