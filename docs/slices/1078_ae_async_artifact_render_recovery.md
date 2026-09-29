# Slice 1078: AE Asynchronous Artifact Render Recovery

## Goal

Harden bounded retry, restart recovery, and metadata-only observability for AE
asynchronous artifact rendering without introducing another persistence table or
reconstructing rendered content from incomplete state.

## Changes

- Added a recovery projection that compares durable render metadata with the
  service-local queue job and reports attempts, retry schedule, dead-letter
  state, safe failure code, and the next recovery action.
- Added exact-owner recovery inspection and reconciliation routes.
- Added deterministic reconciliation for retry, claim, cancellation, and
  terminal failure state drift.
- Preserved fail-closed handling for missing render state, completed queue jobs
  without completed artifact metadata, and other unsafe state combinations.

## Decisions

- Existing common JobQueue bounded retry remains the execution policy source of
  truth. S108 does not add another retry counter or schedule.
- Generic dead-letter replay is not used for artifact recovery because a new
  queue identity would not match the immutable render request and domain render
  job identity. Dead-lettered renders require manual review until a dedicated
  replay contract is explicitly introduced.
- Reconciliation mutates metadata only. It never synthesizes artifact versions,
  rendered files, private payloads, or successful completion.
- A missing queue job asks the caller to repeat idempotent admission; a missing
  render job with a queue record remains blocked for manual review.

## Verification

```bash
scripts/quality/run_slice_gate.sh --service nex-ae-api \
  --test tests/test_ae_async_artifact_render_recovery.py \
  --test tests/test_ae_async_artifact_render_worker.py \
  --test tests/test_ae_async_artifact_render_admission.py \
  --test tests/test_nex_ae_artifacts.py \
  --coverage-target services/nex-ae-api/nex_ae_api/async_artifact_render_recovery.py
```

Observed evidence:

- Slice Gate: `PASS` (`2643 passed`, `4 skipped` protected PostgreSQL tests)
- Overall statement coverage: `98.03%`
- Overall branch coverage: `96.09%` (up from `96.05%`)
- Recovery module statement coverage: `100.00%`
- Recovery module branch coverage: `100.00%`
- Contract validation: `103` schemas, `161` examples, `124` negative
  examples, and `7` OpenAPI documents
