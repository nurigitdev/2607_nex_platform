# Slice 1074: AE Asynchronous Artifact Render Admission

## Goal

Persist one idempotent AE render job and one durable common queue job for every
validated asynchronous artifact render request.

## Changes

- Added content-free `ae.artifact.render` common jobs with deterministic job and
  idempotency identity, owner-bound source request payload, bounded attempts,
  and owner-safe links.
- Added idempotent initial render-job persistence to both in-memory and
  SQLAlchemy artifact stores.
- Added admission states `ENQUEUED`, `JOINED`, and `RECOVERED`.
- Added retry convergence for the case where render metadata is durable but a
  queue write fails before admission completes.

## Decisions

- Artifact metadata is persisted before queue admission. A transient queue
  failure leaves a recoverable `QUEUED` render record; replaying the same
  request completes admission without duplicating the render record.
- Queue payloads contain source and lineage identifiers and hashes, never source
  text, generated response content, rendered bytes, storage paths, or secrets.
- The render job and queue job share one deterministic ID, making divergence
  detectable and recovery deterministic.

## Verification

```bash
scripts/quality/run_slice_gate.sh --service nex-ae-api \
  --test tests/test_ae_async_artifact_render_admission.py \
  --test tests/test_nex_ae_artifacts.py \
  --coverage-target services/nex-ae-api/nex_ae_api/async_artifact_rendering.py
```

## Observed Evidence

- Admission tests: `24 passed`; combined contract/admission tests: `88 passed`.
- SQLite regression proves idempotent initial render persistence, missing
  artifact rejection, and NULL queued timestamps.
- Slice Gate: `2579 passed`, `4 skipped` protected PostgreSQL tests.
- Coverage: statement `98.04%`, branch `96.05%`; async render module statement
  and branch coverage `100%`.
- Contracts: schemas `103`, examples `161`, negative examples `124`,
  OpenAPI documents `7`.
