# Slice 0170: CX Retrieval/Processing Schema Checkpoint

## Scope

Slice 0170 closes the current CX persistence adapter pass with a schema
decision checkpoint for the remaining memory-only surfaces.

Implemented:

- `deferred_schema_decisions` in `cx_persistence_gap_audit.v1`
- explicit candidate tables for retrieval packages and document processing runs
- minimum metadata lists for future durable replay, audit, and AG drilldown
- private payload policies for retrieval evidence and processing step summaries
- deferred header-table decisions for zero-token lexical indexes and zero-chunk
  embedding indexes
- audit regression coverage that verifies the decision payload is immutable per
  audit response and does not expose private payloads

## Decision

No new PostgreSQL tables are added in this slice.

`retrieval_packages` and `processing_runs` remain the only CX surfaces with
`postgres_adapter_required=true`. Their schemas should be finalized when the
retrieval runtime and document processing pipeline need durable replay,
retention, or AG historical drilldown.

Candidate future tables:

- `cx_retrieval_packages`
- `cx_retrieval_evidence_items`
- `cx_document_processing_runs`
- `cx_document_processing_steps`

Optional header tables remain deferred:

- `cx_lexical_indexes`
- `cx_chunk_embedding_indexes`

These header tables are only needed if zero-token lexical indexes or zero-chunk
embedding index attempts must be durably auditable. Current row tables already
cover non-empty lexical terms/postings and chunk embeddings.

## Evidence

Targeted regression:

```bash
./.venv/bin/pytest tests/test_nex_cx_persistence_audit.py
```

Expected result:

```text
5 passed
```

Full quality gate:

```bash
scripts/quality/run_quality_gate.sh
```

Observed result:

```text
1342 passed, 1 warning
statement_coverage=98.26% threshold=95.00%
branch_coverage=94.20% threshold=85.00%
contract_validation=pass schemas=42 examples=66 negative_examples=46 openapi=7
```
