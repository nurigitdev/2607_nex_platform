# Slice 0166: CX Lexical Index Persistence Adapter

## Scope

Slice 0166 adds PostgreSQL-ready persistence for CX lexical index metadata
behind the existing ingestion store and repository boundary.

Implemented:

- `build_lexical_index_record()` metadata mapper for public
  `cx_lexical_index.v1` records
- in-memory and SQLAlchemy repository support for `cx_lexical_terms` and
  `cx_lexical_postings`
- idempotent lookup keyed by `chunk_set_id + tokenizer_used`
- `ContentIngestionStore.save_lexical_index()` write-through to the repository
  when a persisted chunk set is available
- SQLite regression fixture coverage for lexical term/posting DDL shape and
  unique keys
- audit refresh showing lexical index metadata as SQLAlchemy repository ready

## Persistence Boundary

The runtime lexical response remains `cx_lexical_index.v1`; no public route
response shape changed.

The database rows store only:

- persisted chunk set lineage
- tokenizer requested/used/fallback metadata
- fallback state
- term document frequency
- chunk references and occurrence counts
- timestamp metadata

Full chunk text stays outside the lexical tables. The existing schema stores
lexical data as term/posting rows; a zero-token lexical index has no durable
header row in the current schema and is called out for Slice 0170 schema
checkpoint review.

## Evidence

Targeted regression:

```bash
./.venv/bin/pytest tests/test_nex_cx_repository.py tests/test_nex_cx_lexical_index.py tests/test_nex_cx_persistence_audit.py
```

Expected result:

```text
167 passed
```

Full quality gate:

```bash
scripts/quality/run_quality_gate.sh
```

Observed result:

```text
1311 passed
statement_coverage=98.23%
branch_coverage=94.16%
contract_validation=pass schemas=42 examples=66 negative_examples=46 openapi=7
```
