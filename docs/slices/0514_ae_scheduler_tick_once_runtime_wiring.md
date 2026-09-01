# Slice 0514: AE Scheduler Tick-Once Runtime Wiring

## Scope

Wire the AE artifact retention scheduler lease repository into a manual
tick-once runtime path. This slice still does not introduce an always-running
daemon loop.

## Runtime

`run_artifact_retention_scheduler_tick_once(...)` performs one guarded tick:

1. build and acquire a scheduler lease;
2. skip immediately when another held lease is busy;
3. plan artifact retention candidates through the existing artifact store;
4. build the existing scheduler tick plan;
5. enqueue a scheduled retention job when the tick is `READY`;
6. optionally run the existing scheduled worker once;
7. release the scheduler lease in normal and failure paths.

## Result Contract

Tick-once results use
`ae_artifact_retention_scheduler_tick_once_result.v1`.

The result keeps evidence metadata visible:

- lease decision and release status;
- batch plan, tick plan, and enqueue result when a lease is acquired;
- worker summary only when `run_worker=True`;
- daemon, continuous loop, and physical delete automation guardrails;
- metadata-only redaction posture.

## Guardrails

- Scheduler daemon auto-start remains disabled.
- Continuous loop execution remains disabled.
- The runner acquires a lease before planning or queue admission.
- Busy leases skip without touching the artifact store or JobQueue.
- Failures after lease acquisition attempt release in `finally`.
- Physical delete automation remains disabled and the default mode is dry-run.

## Evidence

Regression coverage checks:

- ready tick enqueue through the real in-memory JobQueue;
- no-candidate `NOOP`;
- held-lease busy skip;
- optional worker summary and history-write metadata;
- lease release on failure;
- invalid lease store handling;
- tick-once result validation and helper fallback branches.

## Next

- Slice 0515: Scheduler tick-once PostgreSQL smoke evidence against the AE test
  database.
