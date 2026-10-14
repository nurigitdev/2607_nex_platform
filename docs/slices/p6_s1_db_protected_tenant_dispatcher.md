# P6-S1 DB-Protected Tenant Dispatcher and Capability-Aware Assignment Source

**Status:** COMPLETE
**Date:** 2026-10-14
**Next:** P6-S2 Skill Artifact Gateway

## Scope

P6-S1 connects the P6-S0 worker port to durable AE RuntimeJob selection without
introducing a second queue authority. The existing
`SqlAlchemyRuntimeJobQueue` remains authoritative for job, lease and attempt
state.

Implemented boundaries:

- one active dispatcher leader per queue, protected by a database lease;
- monotonic fencing tokens checked again by leader-owned claim CAS;
- bounded tenant snapshot ordered by oldest runnable work and `tenant_id`;
- at most one tenant visit per round, plus global/per-tenant/round caps;
- executor-kind eligibility inside the claim transaction;
- backend-profile eligibility before claim;
- bounded assignment prefetch bound to one worker identity;
- runnable-depth admission control with explicit `DELAY` or `REJECT` behavior;
- malformed runnable-job dead-letter reconciliation and issue persistence; and
- protected AG read-only aggregate operations visibility.

P6-S1 does not execute `LOCAL_SKILL`. The worker process remains fail-closed
until P6-S4 supplies the execution handler.

## Persistence

Migration `2200_ae_runtime_dispatch` adds:

- `ae_rt_dispatch_lease`: queue leadership, expiry and fencing token;
- `ae_rt_job_issue`: durable malformed-job reason ledger; and
- focused runnable, expired-lease and executor lookup indexes.

The new table and index names remain below PostgreSQL's identifier limit and
are intentionally short enough for routine operations.

## Admission Contract

`NEX_AE_AGENT_DISPATCHER_MAX_RUNNABLE_DEPTH` limits immediately runnable
queued work. Future-scheduled work is not counted as current runnable depth.

- `DELAY`: fail admission with retryable
  `ae.runtime_job_backpressure_delayed` and configured
  `retry_after_seconds`. The caller retains retry authority.
- `REJECT`: fail admission with retryable
  `ae.runtime_job_backpressure_rejected` and no implicit enqueue.
- an idempotent duplicate is returned before capacity rejection.

No process-local cursor or lock is business authority. A restart rebuilds the
next fairness round from durable queue state.

## Operations Boundary

`GET /internal/v1/operations/agent-runtime` is protected by the existing AE
operations trust boundary and admits only `nex-ag` with `operations:read`.
It emits bounded aggregate queue, attempt, latency, leadership, worker,
malformed-issue and job-type data. It includes no tenant, principal, job,
content, credential or provider endpoint values and exposes no mutation route.

The stale-completion metric is reported as `NOT_PERSISTED` instead of inventing
history that the current database does not retain.

## Verification

Focused regression:

```text
82 passed
dispatcher/runtime operations/RuntimeJob focused coverage: 99%
AE Slice Gate: 3522 passed, 5 protected opt-in tests skipped
AE statement coverage: 98.63%
AE branch coverage: 96.86%
contract validation: PASS (174 schemas, 236 examples, 204 negative examples,
7 OpenAPI documents)
```

Actual PostgreSQL protected smoke:

```text
database: nex_ae_test
role: nex_ae_user
migrations: 39 current, latest 2200_ae_runtime_dispatch
checks: 19/19 PASS
jobs exercised: 4
attempts observed: 2
malformed issues observed: 1
remaining rows after cleanup: 0
```

The PostgreSQL evidence covers concurrent leader exclusivity, leader failover,
stale fencing rejection, capability-aware claim, normal completion, expired
lease reclaim, malformed-job dead-letter handling, PostgreSQL query planning,
privacy-safe operations projection and zero residue.

Remote generation, embedding and reranking providers are not needed for this
dispatcher Slice.
