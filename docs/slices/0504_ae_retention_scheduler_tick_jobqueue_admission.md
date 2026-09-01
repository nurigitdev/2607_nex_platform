# Slice 0504: AE Retention Scheduler Tick JobQueue Admission

## Scope

Slice 0504 wires READY scheduler tick plans into the existing AE scheduled
retention JobQueue admission path.

## Behavior

- READY tick plans are converted to the existing
  `ae_artifact_retention_scheduled_job_admission.v1` shape and enqueued through
  the shared JobQueue.
- NOOP and SKIPPED tick plans return metadata-only skipped enqueue results and
  do not touch the queue.
- The wrapper preserves the S50 guarantees: scheduler daemon is not started,
  worker execution is not performed, physical delete automation remains
  disabled, and idempotency stays with the shared JobQueue.

## Evidence

- `services/nex-ae-api/nex_ae_api/artifacts.py`
- `tests/test_nex_ae_artifacts.py`
- `scripts/quality/run_quality_gate.sh`
