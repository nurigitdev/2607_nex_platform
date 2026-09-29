# Slice 1076: AE Asynchronous Artifact Render Worker

## Goal

Execute admitted artifact render jobs through the shared durable worker runtime
without placing source or rendered content in queue, heartbeat, log, or worker
result payloads.

## Changes

- Added a dedicated `ae.artifact.render` worker configuration and once/batch
  runners on the shared JobQueue and WorkerRunner foundation.
- Added owner-scoped CX structured-draft retrieval followed by the existing
  deterministic Markdown, HTML preview, DOCX, and PDF transformation path.
- Added pre-publication cancellation checks, bounded retry transitions,
  terminal dead-letter state, and content-free worker summaries.
- Made artifact version, render-job, file, and link publication idempotent by
  identifier so recovery after a queue-completion interruption does not append
  duplicate metadata.
- Kept retried queue errors internal while publishing failure metadata only for
  terminal failed projections.

## Decisions

- The artifact store owns render metadata and private rendered files; the
  shared service JobQueue owns only content-free execution coordination.
- The persisted artifact owner scope is revalidated against the admitted
  request before every CX call.
- A completed render can safely complete a still-running queue job without
  fetching the structured draft or rendering again.
- Retry scheduling uses the shared bounded JobQueue policy. Later resilience
  slices may add reconciliation and operator recovery without changing this
  execution contract.

## Verification

```bash
scripts/quality/run_checkpoint_gate.sh \
  --test tests/test_ae_async_artifact_render_worker.py \
  --test tests/test_ae_async_artifact_render_admission.py \
  --test tests/test_nex_ae_artifacts.py \
  --coverage-target services/nex-ae-api/nex_ae_api/async_artifact_render_worker.py
```

Observed evidence:

- Checkpoint Gate: PASS (`8208 passed`, `4 skipped`)
- Statement coverage: `98.68%` (`50645/51325`)
- Branch coverage: `96.68%` (`15192/15714`)
- Async artifact render worker: `100.00%` statement, `95.83%` branch
- Contract validation: PASS (`103` schemas, `161` examples, `124`
  negative examples, `7` OpenAPI documents)
