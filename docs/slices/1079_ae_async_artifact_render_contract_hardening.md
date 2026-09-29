# Slice 1079: AE Asynchronous Artifact Render Contract Hardening

## Goal

Freeze the durable request, admission, status, recovery, and reconciliation
surfaces for asynchronous AE artifact rendering as canonical contracts.

## Changes

- Added strict JSON Schemas for the durable render request, admission response,
  lifecycle projection, recovery projection, and reconciliation result.
- Added registered positive examples and explicit negative fixtures for raw
  content, rendered-content flags, storage references, and raw failure detail.
- Published owner-scoped admission, status, cancellation, recovery, and
  reconciliation routes in AE OpenAPI `1.6.0`.
- Added contract tests that validate both checked-in examples and values built
  by the runtime implementation.

## Decisions

- The API create payload is documented separately from the canonical durable
  request because owner/source/lineage fields are derived and validated by AE,
  not accepted from the browser.
- Recovery and reconciliation contracts expose safe failure codes and state
  metadata only. Rendered bytes, storage refs, source content, and raw error
  details remain forbidden.
- The existing synchronous render API stays documented and compatible while
  asynchronous routes remain explicit.

## Verification

```bash
scripts/quality/run_slice_gate.sh --service nex-ae-api \
  --test tests/test_ae_async_artifact_render_contracts.py \
  --test tests/test_ae_async_artifact_render_recovery.py \
  --test tests/test_ae_async_artifact_rendering.py \
  --test tests/test_nex_ae_artifacts.py \
  --coverage-target services/nex-ae-api/nex_ae_api/async_artifact_rendering.py
```

Focused evidence before the Slice Gate:

- Contract tests: `13 passed`
- Contract validation: `108` schemas, `166` examples, `129` negative
  examples, and `7` OpenAPI documents

Observed Slice Gate evidence:

- Slice Gate: `PASS` (`2656 passed`, `4 skipped` protected PostgreSQL tests)
- Overall statement coverage: `98.03%`
- Overall branch coverage: `96.09%`
- Async render state module: statement `99.40%`, branch `98.57%`
- Contract validation: `108` schemas, `166` examples, `129` negative
  examples, and `7` OpenAPI documents
