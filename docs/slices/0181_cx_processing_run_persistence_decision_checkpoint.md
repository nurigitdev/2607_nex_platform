# Slice 0181: CX Processing Run Persistence Decision Checkpoint

## Scope

Slice 0181 freezes the durable persistence shape for CX document processing runs
before adding PostgreSQL DDL or write-through adapters.

Implemented:

- `nex_cx.processing_persistence.build_processing_run_persistence_decision()`
- `nex_cx.processing_persistence.build_processing_run_persistence_preview()`
- `cx_persistence_gap_audit.v1` checkpoint update from Slice 0175 to Slice 0181
- processing run surface status update from unresolved schema deferral to
  `schema_ready_pending_migration`
- regression coverage for private payload key detection, sparse runtime shapes,
  and audit preview redaction

## Decision

Processing run persistence should be split into two future tables:

- `cx_document_processing_runs`
- `cx_document_processing_steps`

The migration is intentionally not added in this slice. The runtime projection
is now fixed first so the schema migration can follow a tested, private-payload
safe shape.

Persistable processing run metadata:

- run identity: `pipeline_run_id`, `pipeline_schema_version`, `document_id`,
  `status`
- trace identity: `trace_id`, `request_id`
- job snapshot metadata: `job_id`, `job_type`, `job_status`,
  `job_attempt_count`, `job_max_attempts`, `job_retryable`, `job_subject_ref`,
  `job_links`
- step summary counters: `step_total`, `step_succeeded`, `step_skipped`,
  `step_failed`
- timestamps: `queued_at`, `started_at`, `completed_at`, `updated_at`

Persistable processing step metadata:

- step identity: `pipeline_run_id`, `step_order`, `step_id`, `status`
- artifact reference metadata: `output_ref_type`, `output_ref_id`,
  `output_ref_document_id`, `output_ref_hash`
- failure metadata: `error_code`, `error_detail_sha256`, `error_retryable`

Private payload exclusions:

- raw source bytes or extracted source text
- extracted markdown text
- chunk text and summary text
- embedding vectors
- generation prompt text
- step `output` payloads
- private data inside `output_ref`
- raw `steps[].error.detail` values

Error details are hash-only in the persistence preview. This keeps AG debugging
correlation possible without making the processing run tables a secondary raw
document or prompt store.

## Next Slice

Recommended next slice:

- `0182_cx_processing_run_step_schema_migration`

## Evidence

Targeted regression:

```bash
./.venv/bin/pytest tests/test_nex_cx_processing_persistence.py tests/test_nex_cx_persistence_audit.py
```

Expected result:

```text
pass
```

Full quality gate:

```bash
scripts/quality/run_quality_gate.sh
```
