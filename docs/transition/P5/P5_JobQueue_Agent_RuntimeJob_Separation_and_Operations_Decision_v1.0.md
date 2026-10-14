# P5 JobQueue and Agent RuntimeJob Separation and Operations Decision v1.0

**Status:** ACCEPTED

**Decision date:** 2026-10-14

**Scope:** P4/P5 Agent Runtime foundation and future multi-user, multi-agent
operations

---

## 1. Decision

NeX Platform SHALL retain two distinct job concepts:

1. `service_jobs` and the shared `nex_runtime.JobQueue` remain the general
   service-local asynchronous work queue.
2. `ae_runtime_job` and `ae_runtime_job_attempt` remain the canonical AE Agent
   Runtime execution ledger.

Their similar enqueue, claim, retry, cancellation, and persistence mechanics do
not by themselves require a shared implementation or a merged table. The two
models protect different invariants and may evolve independently.

This decision does not prohibit later extraction of a small shared primitive.
Extraction requires a demonstrated operational need and SHALL NOT weaken either
domain contract.

---

## 2. Responsibility Boundary

| Concern | Shared JobQueue | AE Agent RuntimeJob |
|---|---|---|
| Primary purpose | General service background work | Durable AgentExecution and ExecutableStep progression |
| Store | service-local `service_jobs` | AE-owned `ae_runtime_job` and `ae_runtime_job_attempt` |
| Identity | JobId, JobType, subject, idempotency key | TenantId, RuntimeJobId, AgentExecutionId, optional ExecutableStepId |
| Execution states | QUEUED, RUNNING, SUCCEEDED, FAILED, CANCELLED | QUEUED, RUNNING, DONE, FAILED, CANCELLED, DEAD_LETTER |
| Retry model | General retry/backoff and replay policy | Technical retry within the same AgentExecution and RuntimeJob |
| Claim safety | PostgreSQL row claim and worker lock metadata | Lease owner, lease token, lease expiry, stale-completion rejection |
| Attempt history | Current aggregate attempt count | Immutable per-attempt ledger including lease expiry |
| Payload rule | General JSON payload | References only; raw prompt/result content is rejected |
| Runtime lineage | Service/job trace lineage | AgentExecution, ExecutableStep, result, and delivery lineage |
| Shared worker support | Common heartbeat/log-enabled WorkerRunner | Dedicated AE execution worker semantics |

The shared JobQueue SHALL NOT be used as an alternate Agent Runtime SoR. The AE
RuntimeJob SHALL NOT replace ordinary artifact, retention, ingestion, or other
service background jobs.

---

## 3. Current Implementation State

The Agent RuntimeJob was introduced in P4, not P5. P5 reuses it for
dependency-aware multi-step execution with deterministic START/CONTINUE jobs.

Current P4/P5 runtime support includes:

- tenant-scoped RuntimeJob identity and deduplication;
- AgentExecution and ExecutableStep lineage;
- lease token and expiry enforcement;
- stale worker completion rejection;
- expired lease reclaim and attempt history;
- deterministic serial-ready step scheduling;
- immutable StepResult and AgentResult lineage;
- restart/dedup PostgreSQL evidence.

Current admission remains intentionally narrower than the future architecture:

- AgentIdentity storage recognizes IA, CA, PA, and EA;
- current PROMPT admission executes project-neutral IA only;
- CA, PA, and EA execution admission is not yet implemented;
- P5 workers are composed and proven by tests/smoke, but no continuously
  running production Agent Runtime worker process exists yet.

This distinction prevents the P5 foundation from being mistaken for a
production-ready multi-agent worker fleet.

---

## 4. Multi-User and Multi-Agent Operations Review

Before real concurrent IA, CA, PA, and EA traffic is enabled, the following
operational capabilities are required.

### 4.1 Dedicated worker process lifecycle

AE needs an independently runnable worker entrypoint and container/process
lifecycle with startup admission, graceful drain, termination handling,
heartbeat, bounded polling, and restart recovery. API processes SHALL admit and
observe work; they SHALL NOT become the implicit long-running worker fleet.

### 4.2 Tenant-aware scheduling and backpressure

The current RuntimeJob claim requires a tenant before selecting work. A future
dispatcher must define how runnable tenants are discovered and served without
allowing one tenant or one busy principal to starve others.

The policy must cover:

- tenant fairness and bounded per-tenant concurrency;
- global worker concurrency and queue-depth limits;
- per-executor capability routing;
- admission backpressure and overload rejection;
- delayed jobs, expired leases, retries, and dead-letter isolation;
- shutdown drain and lease handoff behavior.

Fairness SHALL be based on tenant and execution policy, not user-controlled job
priority. High-cardinality principal identifiers SHALL not become metric
labels.

### 4.3 Runtime observability and AG integration

The current trace projection is sufficient for the P4 compatibility journey,
but it selects one RuntimeJob and one compatibility step. Multi-step and
multi-agent operations require a complete ordered execution timeline.

Minimum operational signals are:

- runnable, running, waiting, retrying, failed, and dead-letter counts;
- oldest runnable age and claim latency;
- execution and step latency distributions;
- attempts, lease expirations, stale completion rejections, and reclaim count;
- throughput and failure rate by bounded job/executor/agent type;
- worker heartbeat, active claims, drain state, and capacity saturation;
- tenant-scoped execution lookup and correlation-based timeline;
- zero raw prompt, response, credential, or private payload leakage.

NeX-AG should consume protected AE operational APIs or projections. It SHALL NOT
claim RuntimeJobs or mutate the AE database directly.

### 4.4 Operator controls

Protected AE controls will eventually be needed for pause/resume admission,
worker drain, safe cancellation, retry/dead-letter review, and bounded replay.
Every mutation must preserve tenant scope, current lease authority, immutable
attempt history, and audit evidence.

---

## 5. Source Ownership and Separation

Source separation SHALL follow responsibility rather than superficial code
similarity.

```text
services/_shared/nex_runtime/
  jobs.py                 general service JobQueue
  worker_runner.py        general service worker lifecycle

services/nex-ae-api/nex_ae_api/
  runtime_jobs.py         AE RuntimeJob persistence and lease authority
  multi_step_engine.py    plan/step scheduling and terminalization
  step_executors.py       executor dispatch and AE result projection
  agent_runtime_foundation.py
                          AE composition and trace projection
```

As the Agent Runtime grows, AE code SHOULD be reorganized behind an
`agent_runtime` package boundary with separate repository, scheduling, worker,
executor, and observability modules. This is a source ownership improvement,
not a requirement to merge it with the shared JobQueue.

Compatibility imports or facades should preserve incremental migration and
keep each refactoring step behavior-neutral.

---

## 6. Refactoring Triggers

No refactoring is required solely because similar code exists. Reconsider a
shared primitive only when one or more of these conditions occurs:

- the same production defect must be fixed independently in both queues;
- a third lease-aware runtime queue is required;
- worker heartbeat/log/recovery integration is repeatedly reimplemented;
- queue semantics drift causes an operational or security defect;
- measured maintenance cost exceeds the cost and risk of a shared abstraction.

Even then, domain tables and state vocabularies may remain separate.

---

## 7. Implementation Priority

The next Agent Runtime expansion should prioritize, in order:

1. dedicated AE worker process and lifecycle;
2. tenant-aware dispatch, fairness, concurrency, and backpressure;
3. complete multi-job/multi-step trace and metrics;
4. protected AE operations API and AG read-only integration;
5. behavior-neutral AE source package separation;
6. only then, evidence-based shared primitive extraction if still beneficial.

These are future implementation requirements. This decision record does not
expand the completed P5 functional scope or claim that CA, PA, or EA execution
is currently available.

---

## 8. Non-Goals

- Merge `service_jobs` and `ae_runtime_job`.
- Replace the Frozen Agent RuntimeJob with `common_job.v1`.
- Move AgentExecution or ExecutableStep authority into the shared runtime.
- Implement CA, PA, EA, WC, NSL, or production worker processes in this record.
- Refactor working code only to reduce line count.
