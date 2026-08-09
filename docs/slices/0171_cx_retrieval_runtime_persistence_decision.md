# Slice 0171: CX Retrieval Runtime Persistence Decision

## Scope

Slice 0171 decides how CX retrieval runtime packages will map into durable
records before adding PostgreSQL tables or adapter write-through.

Implemented:

- `nex_cx.retrieval_persistence.build_retrieval_runtime_persistence_decision()`
- `nex_cx.retrieval_persistence.build_retrieval_package_persistence_preview()`
- audit checkpoint update from Slice 0170 to Slice 0171
- explicit next recommendation:
  `0172_cx_retrieval_package_schema_migration_draft`
- regression coverage for hash/preview-only projection and sparse package
  handling

## Decision

Retrieval package persistence should be split into two future tables:

- `cx_retrieval_packages`
- `cx_retrieval_evidence_items`

The migration is intentionally not added in this slice. The runtime projection
is now fixed first so the migration can follow a tested shape.

Persistable retrieval package header metadata:

- package identity: `retrieval_package_id`, `package_hash`, `status`
- trace identity: `trace_id`, `request_id`
- query metadata: `query_text_sha256`, `query_text_preview`
- query embedding metadata: `query_embedding_provided`,
  `query_embedding_sha256`, `query_embedding_dimension`
- retrieval policy lineage: `retrieval_policy_id`,
  `retrieval_policy_version`, `retrieval_policy_hash`,
  `retrieval_policy_source`, `ranker_mix`, `rerank_state`
- authorization/audit metadata: `permission_snapshot_hash`, `source_summary`,
  `score_summary`, `warning_count`, `evidence_count`, `no_answer_reason`,
  `created_at`, `updated_at`

Persistable evidence item metadata:

- evidence identity: `evidence_id`, `retrieval_package_id`, `rank`
- source lineage: `content_object_id`, `content_version_id`, `chunk_id`,
  `chunk_policy_id`, `source_anchor`, `citation_label`
- evidence text metadata: `evidence_text_sha256`, `evidence_text_preview`
- retrieval metadata: `scores`, `matched_terms`, `permission_result`,
  `neighbor_context`, `quality_flags`

Private payload exclusions:

- `query_text`
- raw query embedding vectors
- `evidence_items[].text`

This keeps AG/debug observability useful without turning retrieval audit tables
into raw prompt or document-snippet storage.

## Evidence

Targeted regression:

```bash
./.venv/bin/pytest tests/test_nex_cx_retrieval_persistence.py tests/test_nex_cx_persistence_audit.py
```

Observed result:

```text
9 passed
```

Full quality gate:

```bash
scripts/quality/run_quality_gate.sh
```

Observed result:

```text
1346 passed, 1 warning
statement_coverage=98.26% threshold=95.00%
branch_coverage=94.22% threshold=85.00%
contract_validation=pass schemas=42 examples=66 negative_examples=46 openapi=7
traceable_mock_flow=pass
generation_recovery_mock_flow=pass
ag_operations_dashboard_smoke=pass endpoints=18 jobs=2 workers=1 events=1 logs=1 history=1 issues=3
ag_job_control_smoke=pass
ag_service_log_retention_smoke=pass
protected_live_rag_smoke=skipped reason=NEX_PROTECTED_LIVE_RAG_SMOKE
postgres_test_smoke_suite=skipped reason=NEX_POSTGRES_TEST_SMOKE_SUITE
```
