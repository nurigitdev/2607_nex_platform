# Slice 0123: CX Document Processing Background Worker

## Scope

Slice 0123 adds an enqueue-first CX document processing path and a one-shot
background worker adapter.

Implemented:

- `POST /api/v1/documents/{document_id}/processing/enqueue`
- `enqueue_document_processing_pipeline()`
- `run_cx_document_processing_worker_once()`
- queued pipeline run records with safe job snapshots
- regression coverage for enqueue-only, worker claim/run, idle worker, and route
  enqueue-to-worker completion

The existing `/processing/run` inline path remains available so current MVP
smokes and local workflows do not break while worker execution is introduced.

## Runtime Behavior

The enqueue path creates or reuses the deterministic processing job and stores a
latest processing record with:

```text
status=QUEUED
steps=[]
job.status=QUEUED
```

The worker path claims `cx.document_processing` jobs through the shared
`run_worker_once()` helper, then runs the existing CX pipeline using the claimed
job's `request_id`, `trace_id`, document subject, and `idempotency_key` as the
pipeline run ID. The CX pipeline still owns step execution, CX lifecycle
operational events, final job completion/failure, and detailed processing
heartbeat metadata.

## Safety Boundary

The background worker remains service-owned in `nex-cx`; `_shared` only owns the
domain-neutral worker runner mechanics. The route does not expose source text,
raw extracted text, provider URLs, or filesystem paths.

## Evidence

Targeted regression:

```bash
./.venv/bin/pytest tests/test_nex_cx_processing.py tests/test_nex_runtime_worker_runner.py
```

Full quality gate:

```bash
scripts/quality/run_quality_gate.sh
```
