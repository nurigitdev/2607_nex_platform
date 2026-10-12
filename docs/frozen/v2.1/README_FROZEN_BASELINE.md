# NeX Platform v2.1 / Agent v2.1 / NSL v0.2 Frozen Baseline Reading Guide

**Status:** READ-ONLY IMPLEMENTATION AUTHORITY GUIDE  
**Frozen root:** `docs/frozen/v2.1/`  
**Current transition branch:** `transition/p4-agent-runtime-foundation`  
**Integrated Freeze Declaration Date:** 2026-10-01

---

## 1. Purpose

This directory contains the frozen Architecture/Contract baseline for:

- NeX Platform v2.1
- NeX Agent v2.1
- NSL v0.2
- Agent ↔ NSL Integration Contract v1.0
- Integrated E2E / Fault / Final Freeze evidence

The Frozen Set is the **target semantic authority** for implementation and transition work.

The current v1.0 source code is the **As-Built implementation reality**.

Transition documents under `docs/transition/` explain how to move from the v1.0 As-Built state to this Frozen target.

> Do not modify Frozen documents to make them match the current source code.

If the current source and the Frozen target differ, record the difference as an implementation/migration issue. Do not silently rewrite either baseline.

---

## 2. Integrated Freeze State

The final integrated declaration is:

`00_FINAL_FREEZE/NeX_Platform_v2.1_Agent_v2.1_NSL_v0.2_Final_Freeze_Declaration_v1.0.md`

It declares:

```text
NeX Platform v2.1
↔ NeX Agent v2.1
↔ NSL v0.2

INTEGRATED E2E CONSISTENCY
= CLOSED / FROZEN

Final Freeze Gates = 15 / 15 PASS

Open E2E-P0  = 0
Open E2E-P1  = 0
Open E2E-PCG = 0
Open E2E-P2  = 0
```

Frozen integrated baselines:

1. NeX Platform v2.1 Final Consistency Closure Working Set v1.8
2. NeX Agent v2.1 Final Frozen
3. NSL v0.2 Final Frozen
4. NeX Agent v2.1 ↔ NSL v0.2 Integration Contract v1.0

Any later semantic change affecting ownership/SoR, identity, authority, approval, Agent↔NSL boundary, WRITE/idempotency/commit/reconciliation, result publication, or recurring work/schedule requires controlled amendment and affected gate re-validation.

---

## 3. Directory Map

```text
docs/frozen/v2.1/
├─ README_FROZEN_BASELINE.md
│
├─ 00_FINAL_FREEZE/
│  ├─ Integrated Final Freeze Declaration
│  ├─ Integrated E2E Validation Plan
│  ├─ Integrated E2E Validation Report
│  ├─ Scenario / Identity / SoR / Fault / Final Gate matrices
│  ├─ Step8 Controlled Amendment closure evidence
│  ├─ Final remaining-issue register
│  └─ SHA256SUMS_FINAL_FREEZE_v1.0.txt
│
├─ 10_PLATFORM_v2.1/
│  ├─ 01_ARCHITECTURE/
│  ├─ 02_DETAILED_DESIGN/
│  ├─ 03_NORMATIVE_V2_1_CONTRACTS/
│  ├─ 04_LEGACY_REFERENCE_CONTRACTS/
│  ├─ 05_NORMATIVE_BASELINE/
│  ├─ 06_REVIEW/
│  ├─ closure / hardening manifests
│  └─ SHA256SUMS_FINAL_v1.8.txt
│
└─ 20_AGENT_NSL_FROZEN/
   ├─ 01_Agent_v2.1_Frozen_12DOCX/
   ├─ 02_NSL_v0.2_Frozen_14MD/
   ├─ 03_Integration_Normative/
   ├─ 04_Final_Validation/
   └─ SHA256SUMS.txt
```

---

## 4. Authority Hierarchy

Use this hierarchy when reading or implementing.

### AUTH-0 — Integrated Final Freeze State

Highest authority for **whether the integrated set is frozen** and for post-freeze change control:

`00_FINAL_FREEZE/NeX_Platform_v2.1_Agent_v2.1_NSL_v0.2_Final_Freeze_Declaration_v1.0.md`

If an older Platform document says the Platform set is "not yet frozen", this final declaration is later and controls the current state.

### AUTH-1 — Frozen Agent / NSL Semantic Authority

Authoritative Agent semantic baseline:

`20_AGENT_NSL_FROZEN/01_Agent_v2.1_Frozen_12DOCX/`

Authoritative NSL semantic baseline:

`20_AGENT_NSL_FROZEN/02_NSL_v0.2_Frozen_14MD/`

Agent↔NSL cross-layer normative contract:

`20_AGENT_NSL_FROZEN/03_Integration_Normative/NeX_Agent_v2.1_NSL_v0.2_Integration_Contract_v1.0.md`

The Agent↔NSL Integration Contract controls the cross-layer boundary. Do not invent a different identity/context/approval/idempotency mapping.

### AUTH-2 — Platform v2.1 Final Architecture Decisions

Read first:

- `10_PLATFORM_v2.1/05_NORMATIVE_BASELINE/NeX_Platform_v2.1_Architecture_Consistency_Closure_and_Unified_Change_Ledger_v1.0.md`
- `10_PLATFORM_v2.1/05_NORMATIVE_BASELINE/NeX_Platform_v2.1_Architecture_Decision_Pack_v1.0.md`

Important frozen responsibility map:

```text
AE-WEB = Workspace / Notification / Human Action surface

AE-API = Agent Registry
       + Unified Agent Runtime
       + Agent↔NSL Integration Layer
       + Skill Artifact Gateway

WC = Enterprise Work SoR
   + Routing / Assignment / Atomic Claim
   + ApprovalWorkItem
   + Recurring Work / Schedule

OA = Authentication / Principal / RoleBinding
   + Effective Authority Context / PDP
   + current authorization

AG = PAP / Governance / Kill-switch
   + Agent / PA / EA-Trust governance
   + NSP / Publisher / Key governance

CX = Context / Evidence Retrieval

MO = Model Serving / deterministic model routing

NSL v0.2 = deterministic atomic Skill execution
         + STRICT WRITE approval semantics
         + actual WRITE IdempotencyKey
         + Commit / Verification evidence

Enterprise OS = Business Transaction SoR
              + Business Formal Approval SoR where required

WA = Work Asset / Post-work Activity / Reporting
   != Scheduler
```

### AUTH-3 — Platform v2.1 Normative Machine-Readable Contracts

Directory:

`10_PLATFORM_v2.1/03_NORMATIVE_V2_1_CONTRACTS/`

These schemas, SQL files and protocol modules are implementation-facing normative contracts.

When a machine-readable contract and an older legacy/reference contract differ, the v2.1 normative contract wins.

### AUTH-4 — Platform Architecture / Detailed Design

Directories:

- `10_PLATFORM_v2.1/01_ARCHITECTURE/`
- `10_PLATFORM_v2.1/02_DETAILED_DESIGN/`

Use them for architecture rationale, requirements, flows, state machines and product boundaries.

### AUTH-5 — Validation / Review Evidence

Directories:

- `00_FINAL_FREEZE/`
- `10_PLATFORM_v2.1/06_REVIEW/`
- `20_AGENT_NSL_FROZEN/04_Final_Validation/`

These establish that the final semantics passed the declared review / E2E / fault gates.

They are validation evidence, not a replacement for the normative design/contracts.

### AUTH-6 — Legacy / Historical Reference

Directory:

`10_PLATFORM_v2.1/04_LEGACY_REFERENCE_CONTRACTS/`

Files marked:

`HISTORICAL_SUPERSEDED`

are historical only.

They may explain design evolution but MUST NOT override the Frozen v2.1 semantic or normative contracts.

---

## 5. Conflict Resolution Rules

When documents appear inconsistent, apply these rules in order.

1. Final integrated Freeze Declaration controls freeze status and post-freeze change control.
2. Frozen Agent v2.1 / NSL v0.2 semantics and the Agent↔NSL Integration Contract control their semantic boundary.
3. Platform v2.1 final Architecture Decision Pack / Closure Ledger control Platform ownership/placement decisions.
4. Later v2.1 controlled amendments and Step8 consolidation override stale pre-amendment assumptions.
5. `03_NORMATIVE_V2_1_CONTRACTS` overrides `04_LEGACY_REFERENCE_CONTRACTS`.
6. `HISTORICAL_SUPERSEDED` files never establish current normative behavior.
7. Do not "reconcile" a conflict by editing Frozen files.
8. Record unresolved implementation conflicts in the current transition Phase Issue Register.

---

## 6. Step8 Final Consolidation Rules — MUST NOT REGRESS

Read:

`10_PLATFORM_v2.1/03_NORMATIVE_V2_1_CONTRACTS/NeX_Platform_v2.1_Controlled_Amendment_Batch10_STEP8_CONSOLIDATION/README.md`

Final consolidated rules include:

### 6.1 Execution Trigger Vocabulary

Canonical new AgentExecution trigger:

```text
ExecutionTrigger = PROMPT | CLAIMED_WORKITEM
```

Do not introduce Event or Schedule as direct new-AgentExecution triggers.

Schedule must materialize Work first:

```text
Schedule
→ Occurrence
→ WorkItem
→ Claim
→ CLAIMED_WORKITEM
→ AgentExecution
```

Events are resume/dependency/result signals, not arbitrary new execution triggers.

### 6.2 Package Trust

Do not restore old proof-before-NSL or raw signed-NSO runtime semantics.

Canonical trust path:

```text
Signed NSP
→ Skill Artifact Gateway
→ PackageTrustEvidence
→ VerifiedSkillArtifact
→ NSL
```

### 6.3 Background Result / WC Claim Lineage

For CA/PA/EA background execution, required WC WorkResult publication must preserve the current claim lineage and required durable ACK before AgentExecution becomes SUCCEEDED.

This is later-phase scope, but P4 must not introduce an incompatible runtime identity/state model.

---

## 7. Current Phase: P4 Agent Runtime Foundation

Current branch:

`transition/p4-agent-runtime-foundation`

P4 must establish the Agent Runtime foundation while preserving v1.0 Chat/RAG behavior.

P4 is intentionally narrower than the complete Frozen target.

### P4 In-Scope Direction

```text
PROMPT
→ AgentExecution
→ RuntimeJob
→ compatibility ExecutableStep
→ existing v1.0 Chat/RAG path
→ AgentResult
```

### P4 Explicitly Not the Place to Implement

Unless the P4 SRS explicitly introduces a compatibility stub/contract only, do not implement:

- WC WorkItem / Claim / Schedule
- CA / PA / EA background execution
- NSL runtime integration
- NSL WRITE
- Approval workflow
- BusinessOperationId write semantics
- Enterprise OS business WRITE
- WA Work Asset pipeline
- recurring work execution

Those belong to later transition phases.

---

## 8. P4 Required Reading — Priority A

Before modifying P4 source code, read these first.

### A0. Final Freeze / Authority

1. `00_FINAL_FREEZE/NeX_Platform_v2.1_Agent_v2.1_NSL_v0.2_Final_Freeze_Declaration_v1.0.md`
2. `20_AGENT_NSL_FROZEN/04_Final_Validation/NeX_Agent_v2.1_NSL_v0.2_Final_Freeze_Declaration_v1.0.md`
3. `10_PLATFORM_v2.1/05_NORMATIVE_BASELINE/NeX_Platform_v2.1_Architecture_Consistency_Closure_and_Unified_Change_Ledger_v1.0.md`
4. `10_PLATFORM_v2.1/05_NORMATIVE_BASELINE/NeX_Platform_v2.1_Architecture_Decision_Pack_v1.0.md`

### A1. Agent v2.1 Runtime Core

From:

`20_AGENT_NSL_FROZEN/01_Agent_v2.1_Frozen_12DOCX/`

Read at minimum:

1. `01_NeX_Unified_Agent_Loop_and_AgentExecution_State_Machine_v0.3_final_consistency_closure_v1.1.docx`
2. `02_NeX_Intent_Resolution_Detailed_Design_v0.2_aligned.docx`
3. `03_NeX_Context_Builder_Detailed_Design_v0.2_aligned.docx`
4. `04_NeX_Plan_Builder_Detailed_Design_v0.3_aligned_consistency_closure.docx`
5. `05_NeX_Plan_Validator_and_Deterministic_Compiler_v0.4_final_consistency_closure_v1.1.docx`
6. `06_NeX_StepExecutionEngine_v0.3_final_consistency_closure_v1.1.docx`
7. `07_NeX_Wait_Resume_Retry_Timeout_Reconciliation_v0.2_final_consistency_closure_v1.1.docx`
8. `08_NeX_Result_Verification_Aggregation_Presentation_v0.2_final_consistency_closure_v1.1.docx`
9. `09_NeX_Runtime_Event_and_Agent_Memory_v0.2_final_consistency_closure_v1.1.docx`
10. `10_NeX_Integrated_E2E_Runtime_Architecture_and_Acceptance_Baseline_v0.3_final_consistency_closure_v1.1.docx`
11. `99_NeX_Agent_Architecture_Unified_Runtime_and_Memory_Baseline_v0.3_final_consistency_closure_v1.1.docx`

`00_NeX_Project_Agent_Architecture_Concept_v0.2_aligned.docx` is also authoritative but is less P4-code-specific than the runtime documents above.

### A2. Platform AE / Runtime / Reliability

Read:

1. `10_PLATFORM_v2.1/02_DETAILED_DESIGN/29_NeX_AE_SRS_and_Detailed_Design_v2.1_FINAL_CONSISTENCY_CLOSURE.docx`
2. `10_PLATFORM_v2.1/02_DETAILED_DESIGN/31_Cross_System_End_to_End_Flow_Design_v2.1_FINAL_CONSISTENCY_CLOSURE.docx`
3. `10_PLATFORM_v2.1/02_DETAILED_DESIGN/32_Reliability_JobQueue_Worker_Recovery_Design_v2.1_CP05_FINAL_HYGIENE.docx`
4. `10_PLATFORM_v2.1/02_DETAILED_DESIGN/33_Integrated_Test_and_Acceptance_Strategy_v2.1_FINAL_CONSISTENCY_CLOSURE.docx`
5. `10_PLATFORM_v2.1/02_DETAILED_DESIGN/36_Implementation_Master_PRD_v2.1_FINAL_CONSISTENCY_CLOSURE.docx`

Architecture context:

- `10_PLATFORM_v2.1/01_ARCHITECTURE/04_NeX_Platform_System_Software_Requirements_Specification_v2.1_FINAL_BACKPROP.docx`
- `10_PLATFORM_v2.1/01_ARCHITECTURE/05_NeX_Master_System_Architecture_v2.1_FINAL_BACKPROP.docx`
- `10_PLATFORM_v2.1/01_ARCHITECTURE/07_NeX_Canonical_Domain_and_Data_Model_v2.1_FINAL_BACKPROP.docx`
- `10_PLATFORM_v2.1/01_ARCHITECTURE/08_NeX_Canonical_API_Event_MCP_A2A_Contract_v2.1_FINAL_BACKPROP.docx`
- `10_PLATFORM_v2.1/01_ARCHITECTURE/09_NeX_Security_Identity_and_Governance_Architecture_v2.1_FINAL_BACKPROP.docx`

### A3. P4 Machine-Readable Runtime Contracts

Read the Batch02 README first:

`10_PLATFORM_v2.1/03_NORMATIVE_V2_1_CONTRACTS/NeX_Platform_v2.1_Controlled_Amendment_Batch02_CP02_CP06/README.md`

P4-relevant AE contracts:

```text
AE/001_ae_agent_registry.sql
AE/003_ae_runtime_job_v2_1.sql
AE/004_ae_reconciliation_v2_1.sql

AE/agent-identity-v2.1.schema.json
AE/agent-session-v2.1.schema.json
AE/execution-trigger-v2.1.schema.json

AE/runtime-job-v2.1.schema.json
AE/runtime-job-attempt-v2.1.schema.json

AE/retry-disposition-v2.1.schema.json
AE/reconciliation-case-v2.1.schema.json
AE/reconciliation-outcome-v2.1.schema.json
AE/reconcile-execution-job-payload-v2.1.schema.json

AE/agent_registry_v2_1.py
AE/execution_trigger_v2_1.py
AE/reliability_protocols_v2_1.py
```

Do not automatically implement the WC/OA parts of the same batch in P4. Read them only as cross-layer constraints when needed.

### A4. Step8 Consolidation

Mandatory:

`10_PLATFORM_v2.1/03_NORMATIVE_V2_1_CONTRACTS/NeX_Platform_v2.1_Controlled_Amendment_Batch10_STEP8_CONSOLIDATION/README.md`

---

## 9. P4 Required Reading — Priority B / Forward Compatibility

These are required to avoid an incompatible P4 model, but they do not authorize P5+ implementation.

### B1. Agent ↔ NSL Boundary

Read:

`20_AGENT_NSL_FROZEN/03_Integration_Normative/NeX_Agent_v2.1_NSL_v0.2_Integration_Contract_v1.0.md`

Critical identity constraints:

```text
AgentExecutionId != NSLExecutionId

AgentExecutionId 1:N NSLExecutionId

NSLExecutionId
= stable across one logical NEW → WAIT → RESUME lifecycle

BusinessOperationId
= separate Agent/Platform-owned semantic operation identity

AgentContext
must not be copied wholesale into NSL runtime_context
```

P4 must reserve a clean extension path for these identities but MUST NOT implement NSL integration yet.

### B2. Result Publication Boundary

Read:

`10_PLATFORM_v2.1/03_NORMATIVE_V2_1_CONTRACTS/NeX_Platform_v2.1_Controlled_Amendment_Batch08_E2E11_RESULT_PUBLICATION/README.md`

Machine-readable contracts:

```text
AE_PUBLICATION/agent-result-v2.1.schema.json
AE_PUBLICATION/result-delivery-v2.1.schema.json
AE_PUBLICATION/result-publication-preflight-v2.1.schema.json
AE_PUBLICATION/publication-reconciliation-case-v2.1.schema.json
AE_PUBLICATION/publication-reconciliation-outcome-v2.1.schema.json
AE_PUBLICATION/reconcile-publication-job-payload-v2.1.schema.json
AE_PUBLICATION/result_publication_protocols_v2_1.py
AE_PUBLICATION/005_ae_result_publication_v2_1.sql
```

Key rule:

```text
AgentExecution may become SUCCEEDED
only after:
  AgentResult is durable
  AND every required ResultDelivery is ACKNOWLEDGED
```

P4 may introduce the AgentResult foundation as defined by the P4 SRS, but must not accidentally create a completion model that makes later ResultDelivery conformance impossible.

---

## 10. Later-Phase Reference — Do Not Implement During P4

### P5 — NSL v0.2

Primary source:

`20_AGENT_NSL_FROZEN/02_NSL_v0.2_Frozen_14MD/`

Also:

- `10_PLATFORM_v2.1/02_DETAILED_DESIGN/16_NeX_NSL_Language_Specification_v0.2_PLATFORM_REBASELINE_v2.1_FINAL_CONSISTENCY_CLOSURE.docx`
- `10_PLATFORM_v2.1/02_DETAILED_DESIGN/17_NeX_NSL_Runtime_and_Certified_Skill_Detailed_Design_v2.1_FINAL_CONSISTENCY_CLOSURE.docx`

### P6 — WC / Background Agent / Claim

- `10_PLATFORM_v2.1/02_DETAILED_DESIGN/14_NeX_Work_Coordination_SRS_v2.1_CP05_FINAL_HYGIENE.docx`
- `10_PLATFORM_v2.1/02_DETAILED_DESIGN/15_NeX_Work_Coordination_Detailed_Design_v2.1_CP05_FINAL_HYGIENE.docx`

### P7 — Approval / WRITE / Enterprise OS

- `10_PLATFORM_v2.1/02_DETAILED_DESIGN/18_NeX_Approval_and_Human_Gate_Detailed_Design_v2.1_CP08.docx`
- `10_PLATFORM_v2.1/02_DETAILED_DESIGN/19_NeX_Enterprise_OS_System_SRS_v2.1_CP04.docx`
- `10_PLATFORM_v2.1/02_DETAILED_DESIGN/20_NeX_Enterprise_OS_Core_Domain_Detailed_Design_v2.0.docx`
- `10_PLATFORM_v2.1/02_DETAILED_DESIGN/21_NeX_NVT_Project_Financial_Ledger_and_PL_Design_v2.0.docx`
- `10_PLATFORM_v2.1/02_DETAILED_DESIGN/22_NeX_Voucher_Accounting_Procurement_Transaction_Design_v2.0.docx`
- `10_PLATFORM_v2.1/02_DETAILED_DESIGN/24_NeX_Enterprise_Business_Core_End_to_End_Golden_Slice_and_Reconciliation_Design_v2.1_CP03.docx`

### P9 — WA / Work Asset

- `10_PLATFORM_v2.1/02_DETAILED_DESIGN/23_NeX_Work_Asset_Human_Effort_and_Labor_Allocation_Design_v2.0.docx`
- `10_PLATFORM_v2.1/02_DETAILED_DESIGN/41_Vertical_Slice_PRD_Work_Activity_and_Periodic_Reporting_v2.1_CP05.docx`

### P10 — Schedule

- `10_PLATFORM_v2.1/02_DETAILED_DESIGN/44_NeX_WC_Recurring_Work_and_Schedule_Detailed_Design_v2.1_CP05.docx`

Do not use AE RuntimeJob scheduling fields as a substitute for WC business Schedule SoR.

---

## 11. Historical / Superseded Documents

The following are intentionally historical:

```text
10_PLATFORM_v2.1/02_DETAILED_DESIGN/
  11_NeX_Coworker_Agent_Runtime_SRS_v2.0_HISTORICAL_SUPERSEDED.docx
  12_NeX_Coworker_Agent_Semi_Autonomous_Detailed_Design_v2.0_HISTORICAL_SUPERSEDED.docx
  13_NeX_Coworker_Agent_Representative_Workflows_v2.0_HISTORICAL_SUPERSEDED.docx
```

They can be used to understand design history.

They must not be used to reintroduce pre-Agent-v2.1 runtime semantics.

Likewise:

`10_PLATFORM_v2.1/04_LEGACY_REFERENCE_CONTRACTS/`

is a legacy/reference area. It does not override current normative v2.1 contracts.

---

## 12. Reading DOCX Files

DOCX originals in the Frozen Set are authoritative artifacts.

Do not edit, resave, normalize, or rewrite them.

For Codex/code analysis, extract text into a temporary untracked location when necessary.

Recommended temporary location:

```text
/tmp/nex-frozen-read/
```

A safe Python extraction pattern is:

```python
from pathlib import Path
from docx import Document

src = Path("docs/frozen/v2.1/.../document.docx")
doc = Document(src)

text = "\n".join(
    p.text
    for p in doc.paragraphs
    if p.text.strip()
)

print(text)
```

If table contents are required, extract them read-only as well.

Do not commit extracted DOCX text into the Frozen directory unless a separate controlled decision explicitly adds a derived-text index.

Machine-readable `.md`, `.json`, `.sql`, `.py`, and `.csv` files should be read directly.

---

## 13. Frozen Integrity Rules

### MUST NOT

Codex or developers MUST NOT:

- edit Frozen DOCX/MD/JSON/CSV/SQL/Python contract files
- rename Frozen files
- reformat Frozen files
- "fix" stale-looking wording directly
- replace Frozen hashes/manifests
- move documents between authority levels
- use legacy reference contracts as current normative contracts
- silently resolve a conflict by changing Frozen content

### MAY

Implementation work MAY:

- read Frozen documents
- extract DOCX text to temporary untracked files
- build derived implementation notes under `docs/transition/`
- cite Frozen file paths from SRS/test plans
- implement new source/database migrations outside the Frozen tree
- record discovered gaps/issues in the transition Issue Register

---

## 14. Relationship to docs/transition

The current transition baseline contains:

```text
docs/transition/
├─ 00_261012_NeX_AsBuilt_Baseline_Record_v1.0.md
├─ 00_261012_NeX_Platform_v1.0_to_v2.1_Transition_and_Conformance_Validation_Plan_v1.0.docx
├─ 01_261012_NeX_Platform_v1.0_AsBuilt_Architecture_Extraction_Report_v1.0.md
├─ 02_261012_NeX_Platform_v1.0_Early_Agent_AsBuilt_Analysis_Report_v1.0.md
├─ 03_261012_NSL_v0.1_AsBuilt_Architecture_and_Runtime_Analysis_Report_v1.0.md
├─ 04_261012_NSL_v0.1_to_v0.2_Delta_and_Implementation_Plan_v1.0.md
└─ 05_261012_NeX_v1.0_to_v2.1_Frozen_Mapping_and_Delta_Consolidation_v1.0.md
```

Use them as:

```text
Frozen Set
= target semantic authority

Transition Plan
= process/order authority

As-Built reports
= current implementation interpretation

P4 SRS
= current-phase implementation scope authority

Source code
= actual implementation reality
```

If a transition document appears to conflict with the Frozen semantic baseline, Frozen wins and the discrepancy must be recorded.

---

## 15. Required Codex Reading Sequence for P4

Before code modification:

```text
STEP 0
Read this README completely.

STEP 1
Read A0 Final Freeze / Authority documents.

STEP 2
Read A1 Agent v2.1 Runtime Core documents.

STEP 3
Read A2 Platform AE / Runtime / Reliability documents.

STEP 4
Read A3 Batch02 machine-readable Runtime contracts.

STEP 5
Read A4 Step8 Consolidation.

STEP 6
Read B1 Agent↔NSL Integration Contract for future-compatible identity boundaries.

STEP 7
Read B2 Result Publication boundary for future-compatible completion/result semantics.

STEP 8
Read docs/transition 00 → 05 in order.

STEP 9
Read P4 Agent Runtime Foundation SRS when present.

STEP 10
Inspect the current transition branch source code.

STEP 11
Produce an implementation plan before modifying code.
```

Do not skip directly from Frozen documents to code changes.

---

## 16. Codex Pre-Implementation Output

Before changing source, Codex should produce:

1. current v1.0 state summary
2. P4 target state summary
3. identity mapping
4. persistence/migration plan
5. files to add/change
6. refactoring required before feature work
7. API compatibility impact
8. unit/contract/regression/smoke/Playwright test plan
9. rollback/feature-flag strategy
10. unresolved issues / conflicts

Only after this review should implementation begin.

---

## 17. P4 Identity Safety Rules

P4 MUST NOT collapse existing v1.0 identities into target identities.

At minimum preserve:

```text
InteractionId       != AgentExecutionId

CX JobId            != AE RuntimeJobId

CX GenerationId     != ExecutableStepId
CX GenerationId     != NSLExecutionId

GeneratedResponseId != AgentResultId

request_id          != BusinessOperationId
```

Migration should add explicit references, not rename existing objects into new semantic identities.

---

## 18. Stop Conditions

Stop implementation and record an issue if any of the following is encountered:

- a required P4 behavior would violate a Frozen invariant
- a current source identity cannot be mapped without semantic collapse
- a proposed migration requires modifying the Frozen baseline
- P4 implementation unexpectedly requires WC/NSL/WRITE/Approval/EOS/WA/Schedule semantics
- a normative machine-readable contract conflicts with a Frozen final semantic document
- a required Agent/Platform contract is ambiguous enough to change ownership/SoR
- a change would require re-opening Frozen E2E/Fault gates

Do not silently choose an interpretation in those cases.

---

## 19. Final Rule

> **Frozen Set defines where the architecture must end.  
> As-Built source defines where implementation starts.  
> Transition documents define how to move between them.  
> P4 SRS defines what this branch is allowed to implement now.**

This README is a reading/navigation and authority guide only.  
It does not amend or replace any Frozen semantic document.
