# P6-S1A Runtime Dispatch Semantic Hardening

**Status:** COMPLETE
**Date:** 2026-10-14
**Predecessor:** P6-S1 DB-Protected Tenant Dispatcher
**Next:** P6-S2 Skill Artifact Gateway

## Purpose

P6-S1A corrects two dispatch semantics without replacing the P6-S1 dispatcher,
the `ae_runtime_job` system of record, or its persistence model.

The closure rules are:

```text
DispatchIssueId != ReconciliationId

platform-known executor + no currently capable worker
  = QUEUED + NO_CAPABLE_WORKER

platform-unknown executor or malformed step reference
  = DEAD_LETTER + ae_rt_job_issue
```

No table, column, constraint, index, or migration was added.

## Source and Refactoring Audit

The audit found that P6-S1 used one worker's advertised executor kinds as the
malformed-job catalog. A `LOCAL_SKILL`-only worker therefore caused valid P5
executor jobs to be classified as `EXECUTOR_UNSUPPORTED`. The dead-letter
update also copied `ae_rt_job_issue.issue_id` into
`ae_runtime_job.reconciliation_id`, conflating two independent identities.

The minimum correction reuses:

- the P5 executor registry in `step_executors.py`;
- the P6 `LOCAL_SKILL` executor declaration;
- the existing `(tenant_id, runtime_job_id)` unique issue lookup boundary; and
- current Agent Runtime worker heartbeat metadata.

## Runtime Semantics

The platform-known executor catalog is now:

- `P4_CHAT_RAG_COMPATIBILITY`;
- `DETERMINISTIC_AGGREGATE`;
- `DETERMINISTIC_REPORT`; and
- `LOCAL_SKILL`.

Malformed reconciliation applies only to:

| Condition | Issue reason | Result |
| --- | --- | --- |
| `executable_step_id` is null | `STEP_ID_MISSING` | `DEAD_LETTER` |
| referenced step does not exist | `STEP_NOT_FOUND` | `DEAD_LETTER` |
| `executor_kind` is null | `EXECUTOR_KIND_MISSING` | `DEAD_LETTER` |
| executor is absent from the platform catalog | `EXECUTOR_UNSUPPORTED` | `DEAD_LETTER` |
| executor is known but unsupported by the current worker pool | no issue | remain `QUEUED` |

`EXECUTOR_UNSUPPORTED` therefore means unknown to the Platform, not merely
unsupported by one worker profile.

## Identity Boundary

`ae_rt_job_issue.issue_id` remains the identity of a dispatch diagnosis.
`ae_runtime_job.reconciliation_id` is reserved for future Agent
Reconciliation and is never assigned by malformed-job handling.

An issue is retrieved through the existing unique relationship:

```text
(tenant_id, runtime_job_id) -> ae_rt_job_issue
```

If a RuntimeJob already carries an Agent Reconciliation ID, dead-letter
processing preserves it unchanged.

## Operations Visibility

The protected AG Agent Runtime projection now compares runnable, platform-known
executor demand with fresh `IDLE` or `BUSY` Agent Runtime worker heartbeat
capabilities. Demand that has no capable worker is emitted as:

```json
{
  "operational_state": "NO_CAPABLE_WORKER",
  "no_capable_worker_count": 1,
  "executor_counts": {"DETERMINISTIC_REPORT": 1},
  "active_executor_kinds": ["LOCAL_SKILL"],
  "bounded_executor_labels": true
}
```

Only the bounded platform executor catalog can become a metric label. Tenant,
principal, RuntimeJob, content, credential, and endpoint identifiers remain
excluded. This projection is read-only and does not mutate or settle work.

## Verification

Focused P5/P6 regression:

```text
220 passed
```

Changed dispatch/operations module coverage:

```text
30 passed
combined coverage: 99%
agent_runtime_operations.py: 100%
```

Actual PostgreSQL protected smoke:

```text
database: nex_ae_test
role: nex_ae_user
checks: 22/22 PASS
RuntimeJobs exercised: 5
attempts observed: 2
malformed issues observed: 1
remaining rows after cleanup: 0
```

The PostgreSQL evidence includes migration currency, issue/reconciliation ID
separation, preservation of a known executor job in `QUEUED`, fresh
`LOCAL_SKILL`-only worker capability evidence, `NO_CAPABLE_WORKER` projection,
and zero residue.

AE Slice Gate:

```text
3523 passed, 5 protected opt-in tests skipped
statement coverage: 98.63% (threshold 98.62%)
branch coverage: 96.87% (threshold 96.85%)
contract validation: PASS
  schemas: 174
  examples: 236
  negative examples: 204
  OpenAPI documents: 7
```

Remote generation, embedding, and reranking providers are outside this Slice.
