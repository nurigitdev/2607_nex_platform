# Slice 0402: AE Artifact PostgreSQL Schema Migration Foundation

## Scope

Add the durable PostgreSQL schema foundation for AE-owned artifact handoffs,
artifact records, source refs, versions, render jobs, files, and owner-checked
links.

## Decisions

- AE remains the artifact system of record. CX keeps generation and structured
  draft records, and AE persists only safe lineage identifiers, hashes, status,
  owner/workspace scope, retention refs, and public route metadata.
- Artifact payload bytes and rendered Markdown content are not stored in this
  schema. `ae_artifact_files.storage_ref` remains a logical `ae://artifacts/...`
  reference until the storage adapter slice supplies the private backing store.
- Owner/workspace/query-critical fields are indexed as columns. Nested safe
  metadata such as `actor_claims_ref`, `workspace_ref`, `quality_summary`,
  `template_ref`, and validation snapshots remain JSONB.
- The migration is idempotent and records
  `0402_ae_artifact_persistence_foundation` in `schema_migrations`.

## Evidence

- `./.venv/bin/pytest tests/test_database_schema_foundation.py -q`
  - `20 passed`
- `./.venv/bin/python scripts/db/run_migrations.py --service nex-ae-api --profile test --dry-run`
  - Planned migrations include `0402_ae_artifact_persistence_foundation`.
