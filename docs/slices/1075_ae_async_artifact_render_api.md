# Slice 1075: AE Asynchronous Artifact Render API

## Goal

Expose owner-safe asynchronous render admission, status, and cancellation while
preserving the existing synchronous artifact render route.

## Changes

- Added `POST /api/v1/artifacts/{artifact_id}/async-render-jobs` for explicit
  asynchronous admission with deterministic idempotency.
- Added `GET /api/v1/async-artifact-render-jobs/{render_job_id}` for content-free
  lifecycle polling.
- Added `POST /api/v1/async-artifact-render-jobs/{render_job_id}/cancel` for
  idempotent queued or running cancellation.
- Added in-memory and SQLAlchemy render-state updates and exact browser tenant
  and owner visibility checks.

## Decisions

- Existing `POST /api/v1/artifacts/{artifact_id}/render-jobs` remains the
  compatibility synchronous route.
- Browser access is claim-authoritative and mismatched artifacts or jobs return
  `404`, avoiding cross-owner existence disclosure. Trusted service calls use
  the persisted artifact owner as authority.
- Successful and failed terminal renders cannot be cancelled. Repeated
  cancellation of an already cancelled render returns the same projection.
- API responses contain progress and identifiers only; no source content,
  rendered bytes, private storage references, or filesystem paths are exposed.

## Verification

```bash
scripts/quality/run_slice_gate.sh --service nex-ae-api \
  --test tests/test_ae_async_artifact_render_admission.py \
  --test tests/test_nex_ae_artifacts.py \
  --coverage-target services/nex-ae-api/nex_ae_api/async_artifact_rendering.py
```

Observed evidence:

- Slice Gate: PASS (`2588 passed`, `4 skipped`)
- Statement coverage: `98.03%` (`15599/15913`)
- Branch coverage: `96.06%` (`5262/5478`)
- `async_artifact_rendering.py`: `100%` statement and branch coverage
