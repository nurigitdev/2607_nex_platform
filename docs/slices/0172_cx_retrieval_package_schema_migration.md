# Slice 0172: CX Retrieval Package Schema Migration

## Scope

Slice 0172 adds the PostgreSQL schema for durable CX retrieval package metadata.

Implemented:

- `database/nex-cx/migrations/0172_cx_retrieval_package_persistence.sql`
- `cx_retrieval_packages`
- `cx_retrieval_evidence_items`
- schema regression coverage in `tests/test_database_schema_foundation.py`

## Decision

Retrieval packages are persisted as metadata records, not raw prompt or evidence
storage.

The package table stores query hash, bounded query preview, policy lineage,
permission snapshot hash, source summary, score summary, status, warnings, and
trace IDs. Evidence rows store package-local evidence IDs, rank, content/chunk
lineage, source anchors, citation labels, evidence hash, bounded preview, score
payloads, and final score.

Evidence identity is package-local: `cx_retrieval_evidence_items` uses the
composite primary key `(retrieval_package_id, evidence_id)` and also enforces
`UNIQUE (retrieval_package_id, rank)`.

## Evidence

Targeted regression:

```bash
./.venv/bin/pytest tests/test_database_schema_foundation.py tests/test_db_migration_runner.py
```

Observed result:

```text
29 passed
```
