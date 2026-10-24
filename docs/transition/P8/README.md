# P8 — Controlled WRITE / Approval / Delegation / Enterprise OS
## Design Document Reading Guide

**Status:** P8 DESIGN BASELINE / CA02-CONTROLLED IMPLEMENTATION ENTRY GUIDE  
**Phase:** P8  
**Platform Repository:** `nurigitdev/2607_nex_platform`  
**Platform Entry Baseline:** `ce1fb8cb2373ab8024bd1ee96c5c641a30368c3a`  
**NSL Repository:** `nurigitdev/2608_nsl`  
**Documented NSL v0.2 Candidate:** `5cd81e18ffbedeee83605cd2e6a6cbcab54c1fb6` (UNVERIFIED / NOT ADMITTED)  
**Actual NSL v0.2 Admission:** NOT ESTABLISHED / P8-S01 REQUIRED  
**Date:** 2026-10-21

---

## Current Implementation Status

The metadata above records the historical CA02 entry state. It is preserved
as design history and is not the current implementation status.

```text
Reviewed Branch = transition/p4-agent-runtime-foundation

P8.1   CLOSED
P8.2   CLOSED
P8.2A  CLOSED
P8.3   CLOSED
P8.4   CLOSED
P8.5   CLOSED
P8.6   CLOSED
P8.7   CLOSED
P8.7A  CLOSED through P8-S75H
P8-CA03 CLOSED
P8.8   CLOSED through P8-S86
P8.9   IN PROGRESS; P8-S87 through P8-S91 CLOSED, P8-S92 is the next Slice
```

Current admitted NSL runtime:

```text
distribution    = nex-skill-language
package_version = 0.2.0
wheel            = nex_skill_language-0.2.0-py3-none-any.whl
wheel_sha256     = sha256:862958a5eab982a71bec5ee58b9e530867d6c25f65d8b770efb29ca78ce7f135
```

The historical NSL admission block was resolved by P8-S01 through P8-S06.
The current attachment baseline was closed by P8-S75H. P8-CA03 aligned the
Repository Full Gate with the canonical `96 / 94` policy and made the P8.8
reliability matrix attachment-aware. P8-S76 proved attachment-bearing
commit-acknowledgement loss without blind redispatch, P8-S77 resolved all
three authoritative reconciliation outcomes without duplicate mutation,
P8-S78 proved that deterministic verification failure preserves the committed
Voucher and exact attachment lineage, P8-S79 proved the same invariant for a
timed-out, unknown verification outcome, P8-S80 proved that publication ACK
loss retries the stable outbox event without repeating business or object
mutation, and P8-S81 proved that approval-event ACK loss creates one semantic
resume and one checkpoint consume while preserving exact approval lineage.
P8-S82 proved that a worker crash after durable checkpoint persistence
recovers the exact wait/resume identity without duplicating ApprovalRequest,
approval wait, WorkItem, payload/manifest reference, or checkpoint consume.
P8-S83 proved with two admitted-wheel processes that a worker crash after
durable WRITE_REQUESTED and EOS commit recovers only through the authoritative
EOS read model, performs no live WRITE redispatch, and preserves the exact
attachment manifest/object identity. P8-S84 proved that current OA trust and
authorization revocation fail closed before every new protected action. P8-S85
proved the tamper and cross-tenant matrix at the owning AE, WC, OA, EOS, and
RustFS boundaries with zero unauthorized mutation. P8-S86 then ran every
P8-S76 through P8-S86 protected fault variant against the actual AE/WC/OA/EOS
test databases and digest-pinned RustFS. Its complete attachment-bearing
journey recovered an intentionally lost EOS commit acknowledgement through
reconciliation, completed actual post-WRITE verification, preserved one
Voucher and one version of each object, and left zero database or object
residue after cleanup. P8-S87 then closed contract, OpenAPI, positive/negative
example, producer/consumer parity, terminology, and reference hygiene across
191 schemas, 255 positive examples, 221 negative examples, 9 OpenAPI
documents, 1,050 references, 25 parity checks, and 21 terminology checks. It
also registered two valid existing positive examples that had not been
indexed. P8-S88 then ran all 17,349 repository tests: 17,238 passed, 111
explicit protected environment guards skipped, and zero failed or errored.
The same JUnit evidence showed zero P7 or Claim/WorkResult failure/error.
P8-S89 then repeated the same complete repository population with canonical
coverage enabled over `services`, `scripts`, and `providers`: all 17,349 cases
retained the S88 result while statement coverage reached 96.72% and branch
coverage reached 96.11%. The existing `96 / 94` floor passed without changing
the coverage source roots, threshold, or sole `*/__init__.py` omission. NSL
native certification remains independent of the Platform denominator and its
admitted identity is unchanged. P8-S90 then guarded and freshly reset the
actual AE/WC/OA/EOS test databases, applied all 105 current migrations, and
ran 74 selected PostgreSQL cases with zero skip or failure. Forty of those
cases were protected skips in the default S89 profile and actual executions in
S90. Baseline and post-suite row-count/content fingerprints matched across all
133 public tables, proving zero database residue. P8-S91 then composed the S43
and S74 authenticated approval journeys into an actual OA/WC/EOS PostgreSQL
and Chromium full gate. All four selected tests ran without skip or failure,
covering `NSL_WRITE`, `BUSINESS_FORMAL`, approve, reject, expired,
unauthorized, exact replay, and domain separation. Responsive desktop/mobile
captures exposed and closed one long formal-summary overflow; the complete AE
Web regression passed `375` tests and the three databases retained zero S91
tenant residue. Before continuing to P8-S92,
read
`P8_8_Pre_Entry_Repository_Consistency_and_Reliability_Preparation_Actions_v1.0.md`
as the normative P8-CA03 amendment to the P8.8 reliability matrix and
`docs/slices/p8_s76_unknown_commit_state_fault_injection.md` plus
`docs/slices/p8_s77_reconciliation_outcomes.md` and
`docs/slices/p8_s78_committed_verification_failed.md` and
`docs/slices/p8_s79_committed_verification_unknown.md` and
`docs/slices/p8_s80_outbox_publication_ack_loss.md` and
`docs/slices/p8_s81_approval_event_ack_loss.md` and
`docs/slices/p8_s82_worker_crash_after_checkpoint.md` and
`docs/slices/p8_s83_worker_crash_after_write_requested.md` and
`docs/slices/p8_s84_trust_authorization_revocation.md` and
`docs/slices/p8_s85_tamper_cross_tenant_matrix.md` and
`docs/slices/p8_s86_full_reliability_protected_gate.md` plus
`docs/slices/p8_s87_contract_openapi_example_hygiene.md` and
`docs/slices/p8_s88_full_repository_regression.md` and
`docs/slices/p8_s89_coverage_closure.md` and
`docs/slices/p8_s90_actual_db_full_gate.md` and
`docs/slices/p8_s91_ia_playwright_full_gate.md` as execution evidence.

---

# 1. Purpose

This README is the entry point for the P8 design document set.

P8 introduces the first authoritative business WRITE path in NeX Platform:

```text
Natural Language
→ Agent Planning
→ deterministic validation / compile
→ NSL v0.2
→ Approval
→ WriteGuard
→ Idempotency
→ Enterprise OS
→ CommitState
→ Verification
```

At the same time, P8 also introduces:

```text
WC Delegation Guard
Human Approval
EOS Organization
NVTProject / Project hierarchy
VoucherDraft
Voucher attachments / RustFS references
Formal Business Approval
Reconciliation
```

Because these concerns cross multiple authoritative domains, the P8 documents
must be read in order.

---

# 2. Recommended Reading Order

```text
① P8 Pre-Architecture Decision
        ↓
② P8 Source Audit
        ↓
③ P8-CA01 Contract Closure
        ↓
④ P8-CA01A NVT / Voucher Attachment Amendment
        ↓
⑤ P8-CA02 Source-Backed Entry / Consistency Closure
        ↓
⑥ P8 SRS
        ↓
⑦ P8 Implementation Slice Plan
        ↓
Implementation
```

Do not start from the Implementation Slice Plan alone.

The Slice Plan assumes all architectural and contract decisions in documents
①~⑥ are already understood and accepted.

---

# 3. Document ① — Pre-Architecture Decision

## File

```text
P8_Pre_Architecture_Decision_Controlled_WRITE_Approval_and_Enterprise_OS_v1.0.md
```

## Read First Because

This document establishes the architectural direction before detailed source
inspection and SRS design.

It answers:

```text
Where does NSL v0.2 live?
Where does Enterprise OS live?
Who owns Organization?
Who owns Approval?
Who owns Delegation Guard?
How are NSL WRITE and business approval separated?
What is the initial P8 implementation sequence?
```

## Key Decisions

```text
NSL v0.2 stays in independent repository
Separate Repository != Separate Runtime Process

NeX-EOS starts in Platform monorepo
EOS starts as modular monolith

NSL = deterministic WRITE safety
EOS = authoritative business semantics

WC = Work / Human Work coordination
OA = Identity / current authorization
IA = interaction channel, not SoR

Delegation Guard = WC responsibility

Approval domains remain distinct

PART_LEAD
→ TEAM_LEAD
→ GROUP_LEAD
→ CEO
→ CHAIRMAN
```

## What This Document Does Not Do

It does not prove current source state.

That is the purpose of the Source Audit.

---

# 4. Document ② — Source Audit

## File

```text
P8_Source_Audit_Controlled_WRITE_Approval_and_Enterprise_OS_v1.0.md
```

## Read After Pre-Architecture Because

This document checks the proposed P8 architecture against actual source and
Frozen contracts.

The initial Source Audit reported this conclusion:

```text
NSL v0.2
!= future P8 implementation target

NSL v0.2
= already implemented and certified deterministic WRITE runtime
```

CA02 later found that the documented source commit is not resolvable from the
audited checkout/remote and that the only admitted wheel is version `0.1.0`.
Treat the conclusion above as design-history input, not current release
evidence. P8-S01 must establish the actual v0.2 artifact.

Therefore P8 changes from:

```text
implement NSL v0.2
```

to:

```text
admit
integrate
bridge
verify
```

## Initially Reported As-Built Baselines

### Platform

```text
repository = nurigitdev/2607_nex_platform
commit     = ce1fb8cb2373ab8024bd1ee96c5c641a30368c3a
tree       = c0901e9e2af266b400adc07dddd815c77fae2ae1
```

### NSL v0.2 Candidate (Not Admitted)

```text
repository = nurigitdev/2608_nsl
branch     = master
commit     = 5cd81e18ffbedeee83605cd2e6a6cbcab54c1fb6
tree       = 71dbea8cca563867b12acd07462a2dcd42d9a8ac
```

## Source Audit Findings

Verified implemented in NSL v0.2:

```text
Approval suspend / resume semantics
BusinessOperationId
WriteIntent
IdempotencyKey
WriteGuard
WRITE_REQUESTED
CommitState
UNKNOWN_COMMIT_STATE
VerificationStatus
Signed NSP trust
Replay no-live-WRITE safety
Voucher / Project vertical acceptance
```

Still requiring Platform implementation:

```text
NSL v0.2 wheel admission
NSL_V02 backend profile
Approval WorkItem
Approval Wait / Resume bridge
Delegation Guard
Enterprise OS
Organization
VoucherDraft business transaction
Golden A
```

## Important Release Hygiene Finding

The source described as certified still showed stale packaging metadata such
as:

```text
pyproject package version = 0.1.0
```

Therefore the actual released wheel must be independently verified before
Platform admission.

---

# 5. Document ③ — P8-CA01 Contract Closure

## File

```text
P8_CA01_Controlled_WRITE_Approval_Delegation_EOS_Contract_Closure_v1.0.md
```

## Read After Source Audit Because

The Source Audit identifies gaps.

CA01 closes them.

This is the most important contract-boundary document before the SRS.

## Main Closure Areas

```text
CA01-A  NSL v0.2 Release Admission
CA01-B  NSL Approval Request / Evidence Bridge
CA01-C  AE Wait / Resume Generalization
CA01-D  WC ApprovalWorkItem Runtime
CA01-E  EOS Formal Approval / HumanGate Domain
CA01-F  WC Delegation Guard
CA01-G  EOS Organization
CA01-H  Golden A Canonical Business WRITE
```

## Important Decisions

### NSL v0.2

```text
NSL_V02_IN_PROCESS
```

is a distinct Platform runtime profile.

### NSL identity mapping

```text
NSL execution_id
==
Platform nsl_execution_id
```

### Approval

Platform preserves the exact NSL `ApprovalRequest` as protected evidence.

The human workflow uses a metadata-safe projection.

### Wait / Resume

P8 extends wait types:

```text
WORK_RESULT
NSL_APPROVAL
```

Approval SHALL NOT be faked as WorkResult.

### Approval domain

P8 adds:

```text
BUSINESS_FORMAL
```

and preserves:

```text
NSL_WRITE
!= BUSINESS_FORMAL
!= AGENT_FORMAL
```

### Delegation Guard

Initial policy:

```text
max_delegation_depth       = 10
max_children_per_work_item = 5
max_descendants_per_root   = 50
cycle_detection            = ENABLED
```

Nested delegation also requires a current valid parent Claim.

### First EOS WRITE

```text
FINANCE.CREATE_VOUCHER_DRAFT
```

---

# 6. Document ④ — P8-CA01A Amendment

## File

```text
P8_CA01A_NVT_Project_Hierarchy_and_Voucher_Attachment_Amendment_v1.0.md
```

## Why It Must Be Read Before the SRS

CA01A adds two business-domain clarifications that are intentionally small but
important.

```text
DEC-21  NVTProject / Project Hierarchy
DEC-22  Voucher Draft Attachment Boundary
```

## NVT / Project Model

```text
NVTProject
    ↓
Mother Project
    ↓
Project Level 2
    ↓
Project Level 3
```

`NVTProject` is a separate EOS business object.

Ordinary Project hierarchy maximum depth is 3.

Mother Project:

```text
parent_project_id = NULL
nvt_project_id    = NOT NULL
```

Child/Grandchild:

```text
parent_project_id != NULL
```

The NVT relationship is resolved through the Mother Project.

## Deferred NVT Scope

P8 does not implement:

```text
token issuance
token accounting
token allocation
token consumption
token valuation
performance scoring
incentive calculation
```

NVTProject is initially an aggregation/business anchor.

## Voucher Attachment Boundary

```text
EOS VoucherDraft
→ attachment metadata / stable object_ref
→ RustFS
```

Binary files are not stored directly in the Voucher relational row.

EOS owns business metadata.

RustFS owns object bytes.

Golden A attachments remain optional.

---

# 7. Document ⑤ — P8-CA02 Entry / Consistency Closure

## File

```text
P8_CA02_Source_Backed_Entry_Baseline_and_Pre_Implementation_Consistency_Closure_v1.0.md
```

## Why It Is Mandatory Before the SRS

CA02 reconciles the initial design set with the source and release artifacts
that are actually available. It formally accepts CA01/CA01A while preserving a
fail-closed P8-S01 gate for the missing NSL v0.2 artifact.

It freezes:

```text
actual NSL source/wheel entry state
CA01/CA01A formal acceptance
canonical Platform and NSL coverage gates
AE ownership of canonical Platform ApprovalEvidence
deterministic Golden A Project/Account/voucher-line resolution
opaque object_ref and authoritative tenant resolver boundary
```

Important entry decision:

```text
admitted NSL v0.2 source/wheel = NOT ESTABLISHED
v0.1 admitted wheel            = valid only for v0.1 profiles
P8 v0.2 runtime activation     = BLOCKED UNTIL P8-S01 PASS
```

---

# 8. Document ⑥ — P8 SRS

## File

```text
P8_Controlled_WRITE_Approval_Delegation_and_Enterprise_OS_SRS_v1.0.md
```

## Read After CA01 / CA01A / CA02 Because

This document converts the architecture and contract decisions into
implementation requirements.

It should be treated as the primary P8 implementation requirements baseline.

## Main Requirement Areas

```text
Release / Version
Identity
NSL v0.2 Integration
Approval Publication
AE Wait / Resume
Approval Evidence
WC ApprovalWorkItem
OA Approval Authorization
IA Human Approval
Formal Business Approval
Delegation Guard
NeX-EOS Foundation
EOS Organization
NVTProject / Project
Account
VoucherDraft
Voucher Attachments / RustFS
Canonical WRITE
EOS Idempotency
Transaction / Outbox
Commit / Reconciliation
Post-Write Verification
Security
Audit / Observability
Persistence
API / Events
Testing
Golden A
Fault / Recovery
```

## Quality Baseline

Platform:

```text
Statement Coverage >= 96%
Branch Coverage    >= 94%
```

NSL repository-native gate:

```text
Statement Coverage >= 99%
Branch Coverage    >= 98%
```

## Golden A

The first authoritative business WRITE is:

```text
User Prompt
→ live planning
→ LOCAL_SKILL
→ NSL v0.2
→ Approval
→ Resume
→ WriteGuard
→ Idempotency
→ WRITE_REQUESTED
→ EOS FINANCE.CREATE_VOUCHER_DRAFT
→ COMMITTED
→ Verification
→ AgentResult
```

---

# 9. Document ⑦ — Implementation Slice Plan

## File

```text
P8_Implementation_Slice_Plan_v1.0.md
```

## Read Last Before Coding

This document converts the SRS into small implementation / testing / commit
units.

The major sequence is:

```text
P8.1   NSL v0.2 Release Admission
P8.2   NeX-EOS Foundation
P8.2A  WC Delegation Guard
P8.3   Human Approval Foundation
P8.4   NSL Approval Suspend / Resume
P8.5   Governed WRITE → EOS
P8.6   Golden A Voucher Draft
P8.7   BUSINESS_FORMAL / Multi-stage Approval
P8.8   Reliability / Reconciliation Closure
P8.9   Full Gate / Final As-Built Freeze
```

The Slice Plan contains:

```text
P8-S01
...
P8-S93
```

Each Slice should be treated as an independent implementation/regression/commit
unit where practical.

---

# 10. First Implementation Batch

Implementation should begin with:

```text
Batch P8-A

P8-S01  Actual NSL v0.2 Wheel Identity Closure
P8-S02  NSL v0.2 Wheel Lock Contract
P8-S03  NSL_V02_IN_PROCESS Backend Profile
P8-S04  Installed v0.2 Package Readiness
P8-S05  v0.2 Public API Adapter Foundation
P8-S06  v0.2 Compatibility Smoke
```

This batch must close before live P8 WRITE integration.

Reason:

```text
All later P8 WRITE / Approval / EOS behavior depends on
the exact NSL v0.2 artifact being known and admitted.
```

---

# 11. Parallel Work After P8.1

After P8.1 closes:

```text
                    P8.1
                     │
          ┌──────────┴──────────┐
          ▼                     ▼
     P8.2 EOS               P8.2A WC
     Foundation             Delegation Guard
          │                     │
          └──────────┬──────────┘
                     ▼
                   P8.3
              Human Approval
                     ▼
                   P8.4
              NSL Wait/Resume
                     ▼
                   P8.5
              Governed WRITE
                     ▼
                   P8.6
                 Golden A
```

P8.2 and P8.2A may proceed in parallel because their authoritative data
boundaries are independent.

---

# 12. Document Authority vs Reading Order

Reading order and authority order are related but not identical.

Recommended reading:

```text
Pre-Architecture
→ Source Audit
→ CA01
→ CA01A
→ CA02
→ SRS
→ Slice Plan
```

Implementation authority:

```text
Frozen Integrated Baseline
> Frozen machine-readable contracts
> certified NSL As-Built
> P7 Final As-Built
> P8 Pre-Architecture
> P8 Source Audit
> P8-CA01 / CA01A
> P8-CA02 for its six scoped consistency decisions
> P8 SRS
> P8 Slice Plan
> implementation convenience
```

If the Slice Plan appears to contradict the SRS:

```text
SRS wins
```

If the SRS appears to contradict CA01/CA01A/CA02:

```text
CA02 wins for its six scoped decisions
CA01 / CA01A wins for other contract-closure decisions
```

If P8 documents contradict Frozen authority:

```text
stop
→ perform source-backed controlled amendment review
```

Do not silently reconcile the contradiction in code.

---

# 13. Key Source Baselines to Keep Beside the P8 Documents

## Platform

```text
P7 Final As-Built Baseline and P8 Handoff
P7 CA02 / CA02A / CA02B closure evidence
Frozen Platform v2.1 contracts
Frozen Approval CP04
Frozen NSL CP03
Frozen Enterprise OS requirements
```

## NSL

The five Frozen v0.2 authority documents:

```text
Architecture Delta Decision Record
Batch A — Execution Contract Alignment
Batch B — Compiler Architecture Alignment
Batch C — Runtime Architecture Alignment
Architecture Consistency Closure / Unified Change Ledger
```

The actual source-backed runtime baseline at CA02 is:

```text
observed source commit = 3b4cb198888570a857e6fb0d3aa077930bb23504
observed package       = nex-skill-language 0.1.0
admitted wheel lock    = deployment/locks/nsl-v0.1-wheel.json
admitted v0.2 source   = NOT ESTABLISHED
admitted v0.2 wheel    = NOT ESTABLISHED
```

The exact v0.2 source, tree, package version, wheel digest, and public API
become authoritative only through the P8-S01 admission lock.

---

# 14. Important P8 Invariants

Do not lose these while implementing individual Slices.

```text
LLM Candidate != Execution Authority

WorkItem creation != Agent execution authority

Claim + Assignment = background Agent execution authority

NSL WRITE Approval != BUSINESS_FORMAL Approval

NSL WRITE Approval != AGENT_FORMAL Approval

IA != Approval SoR

EOS Organization != OA Principal identity

EOS approver resolution != OA authorization

BusinessOperationId remains stable across wait/resume/reconciliation

IdempotencyKey != PayloadHash

UNKNOWN_COMMIT_STATE → no blind retry

COMMITTED + Verification FAILED → no WRITE retry

NSL source repository != Platform source repository

RustFS object bytes != EOS Voucher business metadata
```

---

# 15. P8 Project Model at a Glance

```text
NVTProject
    │
    ├─ Mother Project
    │    ├─ Level-2 Project
    │    │    └─ Level-3 Project
    │    └─ Level-2 Project
    │
    └─ Mother Project
```

Rules:

```text
NVTProject = separate EOS object

Mother Project:
  parent_project_id = NULL
  nvt_project_id    = NOT NULL

Project depth <= 3

cycle forbidden
```

---

# 16. P8 Approval Model at a Glance

```text
                 Human
                   │
                   ▼
              IA / AE-WEB
                   │
                   ▼
             WC ApprovalWorkItem
                   │
         fresh OA authorization
                   │
          ┌────────┴────────┐
          ▼                 ▼
      NSL_WRITE       BUSINESS_FORMAL
          │                 │
          ▼                 ▼
         NSL               EOS
 Approval binding     ApprovalPolicy /
  validation          Instance / Stage
```

One UI may present both.

Their authoritative semantics remain separate.

---

# 17. P8 WRITE Model at a Glance

```text
NSL WriteIntent
     ↓
ApprovalEvidence
     ↓
WriteGuard
     ↓
IdempotencyKey
     ↓
WRITE_REQUESTED
     ↓
EOS current authorization
     ↓
FINANCE.CREATE_VOUCHER_DRAFT
     ↓
CommitState
     ↓
Verification
```

At no point does an LLM directly perform the business mutation.

---

# 18. P8 Delegation Guard at a Glance

```text
current work:delegate
AND
current parent Claim if nested
AND
depth <= 10
AND
direct children <= 5
AND
root descendants <= 50
AND
no Agent cycle
→ child delegation admitted
```

At Claim:

```text
candidate Agent must not appear in ancestor delegating Agent chain
```

---

# 19. Voucher Attachment Model at a Glance

```text
VoucherDraft
    │
    ├─ business fields
    ├─ attachment metadata
    └─ stable object_ref
             │
             ▼
           RustFS
```

EOS SHALL NOT use:

```text
presigned URL
access key
secret key
local path
```

as durable attachment identity.

---

# 20. Implementation Stop Conditions

Stop implementation and return to contract review if code appears to require:

```text
modifying NSL semantics in Platform
direct cross-service DB WRITE
BUSINESS_FORMAL == NSL_WRITE
Approval as fake WorkResult
LLM-selected final approver
LLM-controlled delegation budget
blind retry after UNKNOWN_COMMIT_STATE
WRITE retry after COMMITTED + Verification failure
Project depth > 3 by hidden exception
NVTProject folded into ordinary Project without review
RustFS credential persisted as Voucher attachment identity
NSL_V02_IN_PROCESS activated without an admitted v0.2 wheel lock
LLM candidate treated as final ProjectRef, AccountRef, or voucher-line policy
tenant ownership inferred by parsing object_ref or an internal RustFS key
```

These are architecture violations, not implementation shortcuts.

---

# 21. Recommended Workflow for Each Slice

```text
1. Read relevant SRS requirements.
2. Read matching CA01/CA01A decision.
3. Inspect exact current source.
4. Refactor first if necessary.
5. Add/modify contract first for cross-service changes.
6. Implement one bounded behavior.
7. Add boundary / robustness / worst-case tests.
8. Run focused regression.
9. Run PostgreSQL / Playwright protected test where applicable.
10. Confirm coverage.
11. Commit.
12. Synchronize remote.
13. Record evidence.
14. Move to next Slice.
```

---

# 22. Final Reading Checklist

Before beginning `P8-S01`, the implementer should have read:

```text
[ ] P8 Pre-Architecture Decision
[ ] P8 Source Audit
[ ] P8-CA01 Contract Closure
[ ] P8-CA01A Amendment
[ ] P8-CA02 Entry / Consistency Closure
[ ] P8 SRS
[ ] P8 Implementation Slice Plan
```

For NSL-related slices after P8-S01 admission also review:

```text
[ ] NSL v0.2 five Frozen architecture authority documents
[ ] actual P8-S01 admitted v0.2 public API / source / wheel lock
```

For EOS Approval slices also review:

```text
[ ] Frozen Approval CP04 contracts
[ ] Frozen Enterprise OS requirement catalog
```

For Delegation slices also review:

```text
[ ] P7 DelegationSpec
[ ] P7 WorkItem
[ ] P7 Claim / Handoff / Final As-Built
```

---

# 23. Current Entry Point

The current P8 design baseline is consistency-closed and ready to start the
protected admission work in P8-S01. NSL v0.2 runtime activation remains blocked
until P8-S01 establishes a real source/wheel baseline and passes admission.

Immediate next action:

```text
P8-S01
Actual NSL v0.2 Wheel Identity Closure
```

Then:

```text
S02 → S03 → S04 → S05 → S06
```

to close P8.1.

---

# 24. Final Position

The P8 document set should be understood as one continuous chain:

```text
WHY / WHO OWNS WHAT
        ↓
Pre-Architecture

WHAT ACTUALLY EXISTS
        ↓
Source Audit

WHAT MUST BE FIXED AT THE BOUNDARY
        ↓
CA01 / CA01A

WHAT IS ACTUALLY ADMITTED AND WHO OWNS THE REMAINING BOUNDARIES
        ↓
CA02

WHAT THE SYSTEM SHALL DO
        ↓
SRS

HOW TO IMPLEMENT AND VERIFY IT
        ↓
Implementation Slice Plan
```

If this reading order is preserved, implementation can evolve incrementally
without losing the original authority, safety, or business-domain boundaries
that motivated P8.
