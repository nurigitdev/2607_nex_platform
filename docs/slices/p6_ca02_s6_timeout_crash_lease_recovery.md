# P6-CA02-S6 Timeout, Crash, and Lease-Recovery Hardening

**Status:** COMPLETE
**Date:** 2026-10-16
**Predecessor:** P6-CA02 S1-S5 Checkpoint Gate
**Next:** P6-CA02 closure planning

## Purpose

This Slice separates three failure authorities that must not be conflated:

```text
In-Process NSL timeout -> NSL cooperative deadline and runtime result
Process-Isolated timeout/crash -> isolated backend-run evidence
Worker death or stalled execution -> AE RuntimeJob lease expiry and reclaim
```

It closes a stale-result window in which a worker could persist a StepResult
after its RuntimeJob lease expired, before the later queue completion check
rejected that worker.

## RuntimeJob Fencing

`SqlAlchemyMultiStepEngine` now verifies the exact persisted RuntimeJob and
attempt before `begin_claim`, `record_waiting`, or `record_outcome` mutates
step state or result state. The check requires one current tuple:

```text
tenant_id
+ runtime_job_id
+ attempt_no / attempt_id
+ worker_id
+ lease_token
+ RUNNING job and attempt
+ lease_until > observed_at
```

On PostgreSQL, the RuntimeJob row is locked in the same transaction that
mutates the ExecutableStep and StepResult. Reclaim cannot race between the
authority check and result persistence. A stale attempt fails retryably with
`ae.multi_step_stale_runtime_job_lease` and cannot publish WAITING or terminal
state.

Claim validation also requires the attempt identity and worker identity to
match the job lease. No new table, column, or migration was needed.

## Settlement Time

`P5StepExecutionWorker` previously reused the pre-execution timestamp when it
persisted an outcome. A slow callback could therefore appear to settle before
lease expiry. The worker now records:

- `started_at` immediately before `begin_claim`;
- `observed_at` after the executor returns or raises; and
- the post-execution timestamp for lease fencing and queue settlement.

Backend-provided business timestamps remain part of the StepResult, but they
do not replace the Platform's current lease-observation timestamp.

## Timeout and Crash Boundary

The initial `NSL_V01_IN_PROCESS` profile continues to declare
`NSL_COOPERATIVE_DEADLINE`. It does not claim hard interruption or native
crash containment. If the worker process disappears without a terminal
backend run, RuntimeJob lease expiry is the recovery authority and no
terminal backend evidence is synthesized.

`NSL_V01_PROCESS_ISOLATED` remains the optional hard-containment profile.
`TIMED_OUT` and `CRASHED` remain distinct, retryable backend-run evidence.
Unit regression and protected smoke verify both statuses.

## PostgreSQL Evidence

The protected smoke connected directly to `nex_ae_test` as `nex_ae_user` and
confirmed migration currency through `2205_ae_nsl_dual_profile`. It then:

1. created a real AgentExecution, plan, step, RuntimeJob, and attempt;
2. left attempt 1 unsettled until its lease expired;
3. reclaimed the same RuntimeJob as attempt 2;
4. rejected attempt 1 before StepResult persistence;
5. completed attempt 2 and recorded its result lineage;
6. confirmed attempt outcomes `LEASE_EXPIRED -> DONE`;
7. confirmed zero stale StepResults and zero synthetic backend runs; and
8. deleted every smoke row.

```text
status: PASS
checks: 19/19
actual PostgreSQL: true
runtime attempts: 2
stale StepResults: 0
synthetic backend runs: 0
cleanup residue: 0
remote provider required: no
```

The first complete Gate exposed an intermittent smoke-only failure: the
process crash probe had a one-second child startup budget and could be
classified as timeout immediately after the full regression load. The crash
startup budget was separated from the deliberate 20 ms timeout probe and set
to 10 seconds. Five consecutive protected smoke reruns passed before the
complete Slice Gate was repeated successfully. Summary output now reports the
exact failed check names.

## Regression and Coverage

Final NeX-AE Slice Gate:

```text
3,890 passed, 6 protected tests skipped
statement coverage: 98.62%
branch coverage: 96.84%
S6 protected smoke scope: 100.00% statement, 100.00% branch
contract validation: PASS
schemas/examples/negative examples/OpenAPI: 174/236/204/7
protected PostgreSQL/process smoke: 19/19 PASS
commands: 5/5 PASS
```

The six skipped tests require unrelated protected PostgreSQL profiles. The
S6 smoke was explicitly enabled and was not skipped.

## Boundary

- No database migration or new table was added.
- RuntimeJob remains the AE execution source of record.
- Lease recovery does not fabricate NSL success or terminal evidence.
- In-process execution remains cooperative; hard containment remains an
  explicit process-isolated profile choice.
- Remote embedding, reranking, and generation providers were not required.
- Full Gate remains due at P6-CA02 closure or before P7 entry.
