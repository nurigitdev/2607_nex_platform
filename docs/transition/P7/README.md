# P7 WC and Background Agent Work Transition Baseline

**Status:** P7-CA01 CLOSED / P7-S1 AUTHORIZED
**Phase:** P7 - Work Coordination + CA/PA/EA Background Agent Work
**Predecessor:** P6.5 Remote Generation Provider Integration Acceptance - CLOSED
**Successor:** P8 Controlled WRITE / Approval / Enterprise OS - NOT ACTIVATED
**Date:** 2026-10-17

## 1. Purpose

P7 connects the P4-P6.5 Agent Runtime to a new NeX-WC Work system of record
without replacing the existing AE planning, execution, NSL READ, result, or
delivery boundaries.

```text
DELEGATE_WORK creates Work.
Claim creates execution authority.
AgentExecution performs the work.
WorkResult returns the result.
RESUME_EXECUTION continues the parent.
```

The controlling ownership rule is:

```text
WC owns Work.
AE owns Agent identity and execution.
OA authorizes actors and service authority.
AG reads redacted operational projections only.
NSL executes admitted deterministic skills.
```

## 2. Document Set

Read the P7 documents in this order:

1. `README.md`
2. `../P6_5/P6_5_Final_AsBuilt_Baseline_and_P7_Handoff_v1.0.md`
3. `P7_Pre_Architecture_Decision_WC_and_Background_Agent_Work_v1.0.md`
4. `P7_Source_Audit_WC_CA_PA_EA_Background_Work_v1.0.md`
5. `P7_WC_and_Background_Agent_Work_SRS_v1.0.md`
6. `P7_Implementation_Slice_Plan_v1.0.md`
7. `P7_CA01_Source_Backed_WC_Background_Agent_Contract_Closure_v1.0.md`
8. `contracts/README.md` and the P7 machine-readable contracts
9. per-Slice As-Built records and the P7 Final As-Built baseline after
   implementation

The Pre-Architecture Decision, Source Audit, SRS, and Slice Plan are
pre-implementation baselines. They do not supersede Frozen v2.1 contracts or
the approved source-backed P7-CA01 closure.

## 3. Authority

```text
Integrated Frozen v2.1 Final Freeze
> Frozen Agent v2.1 / NSL v0.2
> Agent <-> NSL Integration Contract v1.0
> Frozen WC machine-readable contracts
> P6 Final As-Built Baseline
> P6.5 Final As-Built Baseline
> approved source-backed P7-CA01 closure
> this P7 transition document set
> implementation convenience
```

Frozen documents are not edited to match implementation convenience.

## 4. Entry Status

Current status:

```text
P6.5 closure and Full Gate                    = PASS
P7 architecture/source/SRS/slice review       = COMPLETE
P7-CA01 source-backed contract closure        = CLOSED
P7 feature implementation                     = P7-S1 AUTHORIZED
NeX-WC service and migration history           = ABSENT
NeX-WC PostgreSQL dev/test roles and databases = CONNECTIVITY CONFIRMED
```

No P7 feature Slice begins before P7-CA01 closes all P0/P1 contract ambiguity.

P7-CA01 additionally freezes the common runtime reuse boundary: WC domain
records remain service-owned, while technical delivery, retry, dead-letter,
replay, heartbeat, log, and job-control behavior reuse
`services/_shared/nex_runtime`. P7 does not introduce another generic JobQueue.

## 5. Canonical Implementation Sequence

```text
P7-CA01  Source-Backed WC / Agent / Claim / Wait / Result Contract Closure
-> P7-S1 NeX-WC Service + WorkItem Foundation
-> P7-S2 AE CA/PA/EA Agent Registry Runtime
-> P7-S3 Deterministic Routing + Atomic Claim / Assignment
-> P7-S4 ClaimExecutionHandoff + CLAIMED_WORKITEM Admission
-> P7-S5 DELEGATE_WORK Compile / Executor + Durable Wait
-> Checkpoint Gate
-> P7-S6 WorkResult + Event Inbox / RESUME_EXECUTION
-> P7-S7 Background Agent Planning + Existing Runtime Integration
-> P7-S8 Failure / Restart / Idempotency Hardening
-> P7-S9 Actual PostgreSQL + Remote Provider Golden B E2E
-> Repository Full Gate
-> P7 Final As-Built / P8 Handoff
```

## 6. Non-Negotiable Invariants

```text
WorkItem existence != AgentExecution authority
RoutingDecision     != AgentExecution authority
Claim               = background execution authority handoff
CLAIMED_WORKITEM     = the only P7 CA/PA/EA execution trigger
LLM Candidate       != routing, claim, identity, or execution authority
one committed claim handoff -> at most one child AgentExecution
one satisfied wait          -> at most one RESUME_EXECUTION RuntimeJob
Background success requires acknowledged WC_WORK_RESULT delivery
no cross-service database mutation
```

Identity values remain distinct. WorkItem, Assignment, Claim, Agent,
AgentExecution, RuntimeJob, ExecutableStep, NSL execution, AgentResult,
WorkResult, ResultDelivery, WaitRegistration, and Event identifiers must not be
overloaded into one another.

## 7. Initial Supported Profile

P7 initially activates only:

```text
Work source    = AGENT_PLAN_STEP
Assignee       = AGENT
Agent types    = CA | PA | EA
Routing        = deterministic exact eligibility
Execution      = existing P6 Runtime + admitted NSL READ
Planning       = existing P5/P6.5 pipeline with a claimed-work source adapter
Transport      = durable outbox/inbox + authenticated HTTP
Concurrency    = existing serial-ready execution
Result target  = WC_WORK_RESULT
```

The following remain out of scope:

```text
NSL WRITE / Commit / Verification / Reconciliation
Approval
Enterprise OS transaction
Schedule / recurring work
Human or external-agent execution
multi-child parallel fan-out
Kafka requirement
multi-host WC HA
```

## 8. P7-CA01 Closure Checklist

P7-CA01 must freeze at least:

1. NeX-WC package, runtime, database, migration, and configuration topology;
2. exact WorkItem, RoutingDecision, ClaimExecutionHandoff, WorkResult, event,
   delegation, and wait contracts;
3. Agent Registry service API and PA project uniqueness;
4. current OA claim-time and result-submit authorization APIs/scopes;
5. WorkItem creation, claim, handoff, result, event, and resume idempotency;
6. claim lease, generation, reclaim, and stale-authority rules;
7. historical-row-safe AE CLAIMED_WORKITEM persistence and admission;
8. DELEGATE_WORK compile/executor and durable WaitRegistration semantics;
9. event-before-wait and wait-before-event convergence;
10. ResultDelivery ACK and Background Agent completion barrier;
11. exact protected Golden B fixture, cleanup, and evidence policy;
12. the disposition of Frozen-visible but initially inactive states and
    candidate types, including `ACKNOWLEDGED`, HUMAN, and EXTERNAL_AGENT.

## 9. Implementation Guardrails

- Review/refactor the owning source boundary before adding each capability.
- Reuse P5/P6.5 planning and P6 runtime; do not create a second Background
  Agent planner or worker framework.
- Preserve the P6.5 provider boundary: AE calls MO and never a vendor endpoint
  directly.
- New P7 semantic hashes use `nex_runtime.semantic_hashes`; bare legacy digest
  and `sha256:<digest>` representations remain distinct.
- The broader legacy AE hash/digest consolidation is deferred and is not a P7
  feature prerequisite.
- Protected PostgreSQL/provider tests remain opt-in during ordinary regression,
  but fresh actual evidence is mandatory for P7 closure.
- Every P7 Slice records implementation, focused tests, regression, coverage,
  migration/smoke evidence where applicable, commit, and synchronization before
  the next Slice begins.

## 10. Closure Shape

P7 closes only after the Golden B journey proves exactly-once semantic work
across actual AE/WC/OA PostgreSQL boundaries, live MO generation, admitted NSL
READ execution, WC result delivery, parent resume, restart/replay, Full Gate,
and zero owned test residue.

The closure artifact is expected to be:

```text
P7_Final_AsBuilt_Baseline_and_P8_Handoff_v1.0.md
```
