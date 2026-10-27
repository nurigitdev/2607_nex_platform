# P9 NeX-WA Transition Baseline

**Status:** P9 DESIGN SET REVIEWED / P9-CA01 REQUIRED / P9.2 CODING BLOCKED  
**Phase:** P9 - NeX-WA Work Evidence and Work Asset Foundation  
**Platform:** NeX Platform v2.1  
**Predecessor:** P8 v1.2 CLOSED / P9 ENTRY AUTHORIZED  
**Current Entry Gate:** P9-CA01 Frozen WA Reconciliation  
**Date:** 2026-10-27

## 1. Purpose

P9 introduces NeX-WA as a first-class, owner-local service that converts
authoritative post-work source facts into immutable, idempotent WorkEvidence
and bounded WorkAsset records.

P9 is not a scheduler, approval engine, payroll system, accounting system, or
employee performance evaluator. OA, AE, WC, and EOS remain the authorities for
identity, Agent execution, work coordination, and Project state respectively.

## 2. Required Reading Order

Read the P9 documents in this order:

1. `README.md`
2. `../P8/P8_Final_AsBuilt_Baseline_and_P9_Handoff_v1.2.md`
3. `P9_NeX_WA_Pre_Architecture_Decision_v1.2.md`
4. `P9_NeX_WA_Source_Audit_and_Gap_Analysis_v1.0.md`
5. `P9_NeX_WA_Contract_Closure_v1.1.md`
6. `P9_NeX_WA_SRS_v1.1.md`
7. `P9_NeX_WA_Implementation_Slice_Plan_v1.1.md`
8. the approved P9-CA01 Frozen WA reconciliation record, once created
9. per-Slice As-Built records under `../../slices/`, in implementation order
10. the final P9 As-Built and next-phase handoff, once created

The exact repository filenames above are canonical. Historical or descriptive
references with a `261027_` prefix do not replace these actual filenames.

## 3. Document Roles and Authority

The documents have different roles:

```text
P8 executable source + P8 Final As-Built
  = inherited authority and behavior

P9 Contract Closure v1.1
  = closed P9 ownership and semantic boundary

P9 SRS v1.1
  = concrete implementation and acceptance requirements

P9 Implementation Slice Plan v1.1
  = implementation order, Gate cadence, and evidence plan

P9 Pre-Architecture + Source Audit
  = rationale, alternatives, and source-backed findings

Frozen Work Asset references
  = mandatory reconciliation inputs, not silent overrides
```

Implementation convenience SHALL NOT override a higher authority. If Frozen
material reveals a material conflict in ownership, identity, approval,
completion, WorkEvidence, or WorkAsset semantics, implementation stops and a
P9 Controlled Amendment is required.

## 4. Mandatory P9-CA01 Entry Gate

P9 SRS and Slice planning are complete enough to review, but P9.2 production
domain coding is blocked until P9-CA01 passes.

P9-CA01 SHALL materialize and reconcile:

```text
../../frozen/v2.1/10_PLATFORM_v2.1/02_DETAILED_DESIGN/
  23_NeX_Work_Asset_Human_Effort_and_Labor_Allocation_Design_v2.0.docx

../../frozen/v2.1/10_PLATFORM_v2.1/04_LEGACY_REFERENCE_CONTRACTS/
  23_NeX_Work_Asset_Human_Effort_and_Labor_Allocation_Implementation_Contracts_v2.0.zip
```

Each material finding is classified as:

```text
COMPATIBLE
ADDITIVE / INCORPORATE
CONFLICT / CONTROLLED AMENDMENT REQUIRED
NOT APPLICABLE TO P9 FOUNDATION
```

P9-S01 may begin only after the reconciliation record declares coding entry
`PASS` with no unresolved material conflict.

## 5. Canonical Implementation Sequence

```text
P9-CA01  Frozen WA Reconciliation / Coding Entry

P9-S01..S05   owner-local service, DB, WorkEvidence, WorkAsset, local UoW
              -> Checkpoint Gate #1

P9-S06..S10   durable intake, consumer, fenced recovery, core reads
              -> Full Gate / P9-CA02

P9-S11..S15   AE/WC projections and OA/EOS authority contracts
              -> Checkpoint Gate #2

P9-S16..S20   completion-aware admission, equivalence, Human evidence, privacy
              -> Full Gate / P9-CA03

P9-S21..S25   reconciliation, replay, operations, trust, deployment
              -> Checkpoint Gate #3

P9-S26..S30   load, installed runtime, drift, protected E2E, reliability
              -> Full Gate / P9-CA04

P9-S31        Final As-Built / Handoff Freeze
```

P9.5 contribution-candidate Slices `P9-C01..P9-C03` are optional. They may be
activated only after source, authority, attribution, and privacy closure, and
are not required to close the NeX-WA Foundation.

## 6. Non-Negotiable Invariants

```text
WA is post-work evidence, not Work SoR.
WA is not a Scheduler.
WA does not directly read another service database.
OA retains Human identity authority.
AE retains Agent identity and execution authority.
WC retains WorkItem, Claim, Assignment, and Delegation authority.
EOS retains Project and ProjectMember authority.
Evidence admission is not business approval.
WA failure does not invalidate completed source work.
WorkEvidence is immutable or explicitly superseded.
Queue idempotency and evidence idempotency are separate controls.
AgentResult, WorkResult, and Artifact are not independent contribution units.
Positive Agent evidence requires the authoritative completion/ACK barrier.
Stale Job recovery invalidates the prior worker's settlement authority.
Model output is not evidence authority.
Foundation does not require NSL, WC Delegation, or an external broker.
Golden C retains final MM, cost, accounting, and Project P/L authority.
```

## 7. Initial Runtime and Environment

```text
service_id       = nex-wa
API process      = nex-wa-api
consumer process = nex-wa-evidence-consumer
local API port   = 8108
development DB   = nex_wa_dev
test DB          = nex_wa_test
database role    = nex_wa_user
job type         = WA_EVIDENCE_INGEST
```

P9 reuses the shared service-local `nex_runtime.JobQueue`, WorkerRunner, and
WorkerHeartbeat patterns. It does not reuse `ae_runtime_job` as the WA queue.

Remote embedding, reranking, and generation providers are not required for
the mandatory Foundation path. Playwright is not required unless a WA browser
UI is explicitly introduced. Actual PostgreSQL protection begins with P9-S02
and remains mandatory for persistence and recovery closures.

## 8. Current Entry Status

```text
P8 Final As-Built v1.2                 = CLOSED
P9 Pre-Architecture                    = REVIEWED
P9 Source Audit                        = REVIEWED
P9 Contract Closure v1.1               = REVIEWED
P9 SRS v1.1                            = REVIEWED
P9 Implementation Slice Plan v1.1      = REVIEWED
P9-CA01 Frozen WA reconciliation       = NOT STARTED
P9.2 production domain coding          = BLOCKED
```

The next authorized activity is P9-CA01. No P9 production Slice begins before
that gate closes.

## 9. Maintenance Rule

After each accepted Slice:

1. add or update the corresponding `docs/slices/` evidence record;
2. record actual PostgreSQL, protected, Checkpoint, or Full Gate evidence when
   the Slice claims it;
3. preserve the authority and non-goal boundaries in this README;
4. update this entry status only from committed source-backed evidence; and
5. commit and synchronize one completed Slice at a time.
