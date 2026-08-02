# Slice 0021 Persistent Schema Foundation

Status: Implemented.

Backlog candidate: `S3-001` Persistent schema foundation for content,
summaries, prompt registry, and prompt analytics.

Requirement coverage: `CX-FR-001` through `CX-FR-006`, `AEAPI-FR-001`,
`TRACE-PLAT-001`, `MO-FR-004`, `AG-FR-001`.

## Scope

Slice 0021 adds service-owned SQL migration foundations without wiring runtime
repositories yet:

- CX content persistence for source blobs, logical content objects, ACL entries,
  Markdown extraction artifacts, chunk sets, chunks, chunk embeddings, lexical
  terms/postings, document summaries, and document summary embeddings.
- CX active-document dedupe scoped to `tenant_id + owner_user_id +
  source_sha256`, while source blobs keep a global hash for storage-level
  dedupe.
- CX summary records limited to a single summary chunk shape:
  `summary_1000_0`, default 900 characters, hard limit 1000 characters.
- CX prompt registry, prompt template versions, prompt bindings, and prompt
  render event hashes for summary and grounded generation debugging.
- AE chat, prompt registry, prompt events, intent classifications, user task
  profiles, automation recommendations, and recommendation feedback.
- AE prompt analytics stores prompt hashes, previews, normalized labels, and
  outcomes without raw prompt columns.

This slice keeps the current mock-first runtime unchanged. Runtime repository
classes and actual migration execution can be added in later slices once we
choose the migration runner.

## Files

- `database/README.md`
- `database/nex-cx/migrations/0021_content_summary_prompt_foundation.sql`
- `database/nex-ae-api/migrations/0021_prompt_analytics_foundation.sql`
- `tests/test_database_schema_foundation.py`

## Evidence

Slice evidence should include:

```bash
scripts/quality/run_quality_gate.sh
```

Regression tests statically validate service-local migration ownership,
transactional migration shape, active owner-scoped file dedupe, summary length
limits, summary embedding lineage, prompt registry versioning, and raw prompt
exclusion from analytics tables.
