# P7 Final As-Built Baseline and P8 Handoff v1.0

**Status:** FINAL / P7 CLOSED / P8 ENTRY AUTHORIZED
**Phase Closed:** P7 - Work Coordination + CA/PA/EA Background Work
**Next Phase:** P8 - Controlled WRITE / Approval / Enterprise OS
**Observed Date:** 2026-10-19
**Platform Branch:** `transition/p4-agent-runtime-foundation`

## 1. Closed Objective

P7 connected the P4-P6.5 Agent Runtime to NeX-WC without transferring work,
identity, authorization, planning, or execution authority to an LLM. The
closed authority chain is:

```text
DELEGATE_WORK
-> WC WorkItem
-> deterministic route
-> atomic Claim / assignment
-> CLAIMED_WORKITEM AgentExecution
-> existing P5/P6.5 planning admission
-> existing P6 RuntimeJob / in-process NSL READ
-> AgentResult / ResultDelivery
-> acknowledged WC WorkResult
-> AE event inbox / RESUME_EXECUTION
-> parent deterministic continuation
```

## 2. As-Built Ownership

```text
WC  owns WorkItem, RoutingDecision, Assignment, Claim, and WorkResult.
AE  owns AgentIdentity, AgentExecution, plans, RuntimeJobs, waits, and results.
OA  owns actor membership and effective authorization.
MO  owns provider routing, readiness, and model identity projection.
NSL executes only admitted deterministic skills through its public API.
AG  remains a redacted operational projection consumer.
```

Each service owns its database. P7 added `nex-wc` as the sixth service-local
database; it did not create one platform-wide JobQueue or allow cross-service
database mutation.

## 3. Durable and Runtime Baseline

P7 closes with:

- service-owned WC work, route, claim, assignment, handoff, result, and outbox
  records;
- AE CA/PA/EA registry support and `CLAIMED_WORKITEM` admission;
- `WC_DELEGATE_WORK` compilation and `DELEGATE_WORK` execution;
- durable WaitRegistration and exactly-once semantic resume;
- claim generation reclaim and stale-authority rejection;
- ACK-bound child success and immutable WorkResult retry semantics;
- existing P5/P6.5 semantic planning and P6 NSL READ execution;
- existing shared `nex_runtime` technical queue/delivery primitives where
  appropriate, without collapsing service-owned queue instances.

Current migration heads are:

```text
NeX-AE = 2405_ae_claimed_planning_source
NeX-WC = 1002_wc_work_result
NeX-OA = 1376_oa_trace_projection_index
```

## 4. Golden B Acceptance

The final protected journey ran against actual `nex_ae_test`, `nex_wc_test`,
and `nex_oa_test`, live MO generation, and admitted NSL revision
`3b4cb198888570a857e6fb0d3aa077930bb23504`.

```text
provider mode/profile/model = live / general-llm-default / Qwen3.5-4B
semantic stages             = INTENT / CONTEXT / PLAN
prompt bindings             = intent v1 / context v2 / plan v1
OA membership bootstrap     = 1
OA effective auth reads     = 2
WorkResult                  = 1
RESUME_EXECUTION            = 1
parent StepResults          = 2
acceptance checks           = 51 / 51
AE/WC/OA owned residue      = 0
```

Credentials, endpoint values, raw prompts, provider output, private result
content, and hidden reasoning are absent from evidence.

## 5. Closure Verification

| Gate | Result |
| --- | --- |
| Protected P7-S9 Golden B | `16 passed`; 51/51 checks; statement/branch `100%` |
| P7-S8 recovery smoke | 26/26 checks; zero residue |
| AE Slice Gate | `4,513 passed, 16 skipped`; statement `98.29%`; branch `96.14%` |
| WC/P7 Gate | `181 passed`; statement `96.74%`; branch `94.12%` |
| Contract validation | 174 schemas, 236 examples, 204 negative examples, 8 OpenAPI documents |
| Repository Full Gate | `15,386 passed, 47 skipped`; statement `96.87%`; branch `96.27%` |

The P7-S9 runner is protected and remains skipped in ordinary broad regression.
Its actual database/provider execution is separate, explicit, and recorded in
the sanitized live evidence pack.

## 6. P8 Entry Contract

P8 may build additively on these invariants:

1. WorkItem existence and routing never grant execution authority.
2. Only a current active Claim generation can create claimed-work execution.
3. LLM output remains an untrusted candidate, never execution authority.
4. One committed handoff creates at most one child AgentExecution.
5. Background success requires exact WC WorkResult acknowledgement.
6. One satisfied wait creates at most one `RESUME_EXECUTION` RuntimeJob.
7. Retry and restart preserve semantic IDs and do not duplicate results.
8. OA authorization remains fail-closed at claim and result boundaries.
9. Cross-service integration uses authenticated contracts, not shared tables.
10. P8 WRITE, approval, verification, reconciliation, and Enterprise OS
    semantics must not be backfilled into P7 records by convenience.

## 7. Deferred Scope

P7 did not activate NSL WRITE, approval, Enterprise OS transactions, schedules,
human/external-agent execution, multi-child parallel fan-out, Kafka, or
multi-host WC HA. Those capabilities require their own source-backed contract
closure and acceptance in P8 or a later phase.

P7 is closed. P8 entry is authorized only on the baseline above.
