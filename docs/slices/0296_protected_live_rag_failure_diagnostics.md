# Slice 0296: Protected Live RAG Failure Diagnostics

## Scope

Harden the protected live RAG PostgreSQL smoke so failures explain which safe
stage failed instead of only reporting a broad exception class.

This is based on the Slice 0295 live run experience, where grounded generation
initially failed with `cx.retrieval_package_not_ready` because the retrieval
package was `LOW_CONFIDENCE`.

## Implemented

- Added explicit execution stages for:
  - database engine setup;
  - service app setup;
  - upload, extraction, chunking, lexical indexing, embedding indexing;
  - retrieval, generation, provider telemetry;
  - RAG evidence assertion, PostgreSQL observation, checks, redaction, cleanup.
- Added `LiveRagSmokeStageError` with safe diagnostics:
  - `stage`;
  - `error_code`;
  - bounded `detail`;
  - optional `status_code`;
  - optional `retryable`;
  - per-stage status map.
- HTTP problem responses now preserve safe `error_code`, `detail`, status code,
  and retryability in failure evidence.
- Successful evidence now includes `stage_status`, including cleanup.
- Failure summary lines include `stage=<stage>` when diagnostics are available.
- Existing redaction policy also guards failure diagnostics so provider
  endpoints, API keys, database passwords, source text, and local paths stay out
  of evidence.

## Evidence

- Python regression:
  `./.venv/bin/pytest tests/test_protected_live_rag_postgres_smoke.py -q`
- Full quality gate:
  `./scripts/quality/run_quality_gate.sh`
