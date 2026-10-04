# Slice 1349: CX Ingestion Restart, Cancellation, and Cleanup

## Goal

Turn the registered CX ingestion background process from a lifecycle-only
shell into a restart-aware durable worker, and keep job/run state consistent
when cancellation arrives between checkpoints.

## Implementation

- Added a process adapter that loads the durable restart plan once at startup,
  recovers expired leases, and then claims one ingestion job per poll cycle.
- Wired the executable background-process entrypoint to the adapter in the
  protected `test` profile. `local_mock` remains non-claiming because its
  process-local queue cannot be shared with the API process.
- Added a job-state guard before every ingestion checkpoint. A cancelled job
  stops before the next step and durably settles the run as `CANCELLED`.
- Reset a preannounced but unexecuted `RUNNING` step to `PENDING` on
  cancellation, including its attempt and start metadata.
- Added idempotent shutdown cleanup for API and worker database pools.

## Guardrails

- Restart planning and evidence contain metadata only.
- Worker cancellation is cooperative at checkpoint boundaries; an in-flight
  provider call is not force-killed.
- Actual PostgreSQL execution and residue cleanup are assigned to Slice `1350`.
- No table or migration was added.

## Evidence

- Deterministic evidence covers expired-lease recovery, queued work completion,
  checkpoint cancellation, non-running next-step state, and cleanup: `12/12`.
- Process, worker, coordinator, orchestration, and executable-shell focused
  regression: `106 passed`.
- CX Slice Gate: `2,305 passed`; statement coverage `99.07%`, branch coverage
  `98.17%`.
- Ingestion worker process: statement `100%`, branch `100%`.
- Ingestion worker: statement `100%`, branch `100%`.
- Ingestion orchestration: statement `100%`, branch `98.78%`.
- Evidence runner: statement `100%`, branch `100%`.
- Contract validation: `159` schemas, `216` positive examples, `186` negative
  examples, and `7` OpenAPI documents.

## Result

The durable ingestion worker now has an executable work-claiming path and
restart/cancellation behavior suitable for the protected PostgreSQL journey in
Slice `1350`.
