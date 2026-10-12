# P4 Agent Runtime Foundation Issue Register v1.0

**Status:** ACTIVE TRANSITION REGISTER
**Opened:** 2026-10-12
**Scope:** P4 planning and implementation

Severity meanings:

- `P0`: unsafe to continue;
- `P1`: must be decided before affected implementation;
- `P2`: must be closed before P4 acceptance;
- `P3`: documentation or low-risk follow-up.

| ID | Severity | Source | Issue | STEP 8.1 decision | Status / next action |
|---|---:|---|---|---|---|
| P4-ISSUE-001 | P1 | P4 SRS constraint 03 | No standalone machine-readable AgentExecution schema was found. | Use the exact Agent Frozen Doc 01 state and phase vocabulary; do not invent a subset. | `DESIGN_RESOLVED`; STEP 9 records enums and source citation. |
| P4-ISSUE-002 | P1 | P4 SRS constraint 02 | Trusted ACTIVE IA provisioning/resolution policy is not fixed. | Browser agent identity is prohibited; resolve through AE Agent Registry from authenticated server context. | `OPEN_STEP9_SOURCE_AUDIT`. |
| P4-ISSUE-003 | P1 | P4 SRS constraint 01 | PROMPT requires trusted `project_id`, while generic v1.0 Chat may not have one. | No default/fake project; inspect current trusted workspace/project binding and define bypass/failure by rollout mode. | `OPEN_STEP9_SOURCE_AUDIT`. |
| P4-ISSUE-004 | P1 | P4 SRS constraint 05 | Full publication ACK depends on current OA/scope/classification/visibility evidence. | Implement bounded conformant IA `WORKSPACE_RESULT` preflight and durable target confirmation in P4. | `DESIGN_RESOLVED`; source adapter mapping remains STEP 9. |
| P4-ISSUE-005 | P1 | STEP 7 review | Frozen SQL projection cannot reconstruct every required AgentResult schema field by itself. | Add immutable `result_envelope_json` plus normalized projection columns and parity validation. | `DESIGN_RESOLVED`; migration/repository pending. |
| P4-ISSUE-006 | P1 | STEP 7/8 review | P4 SRS did not require atomic AgentResult and required-delivery persistence. | Persist AgentResult, complete required delivery plan, and deduplicated publication job in one AE local transaction. | `DESIGN_RESOLVED`; transaction tests pending. |
| P4-ISSUE-007 | P1 | STEP 7 helper probe | Empty delivery collection can pass a low-level ACK-only helper. | Domain completion guard requires a valid non-empty plan and exactly one required workspace delivery before ACK evaluation. | `DESIGN_RESOLVED`; negative tests pending. |
| P4-ISSUE-008 | P1 | P4-RES-010 | Frozen assets require `result_hash` but do not fix its complete algorithm. | SHA-256 over the STEP 8.1 canonical semantic projection; fixed vectors required. | `DESIGN_RESOLVED`; utility selection pending STEP 9. |
| P4-ISSUE-009 | P3 | P4 SRS line 334 | Rollout mode refers to Section 22, but rollout is Section 23. | Treat the reference as Section 23 without changing Frozen documents. | `DOCUMENTED`; correct in next P4 SRS revision if one is approved. |
| P4-ISSUE-010 | P3 | Transition baseline record | The historical record says the Platform `v1.0` tag was absent. | Preserve the historical record and add an independent tag verification addendum. | `CLOSED` by `00A` addendum. |
| P4-ISSUE-011 | P2 | STEP 7 SQL review | Publication reconciliation outcome has a schema but no explicit append-only SQL outcome store. | External-target reconciliation outcome persistence is deferred to P9 and must not be simulated in P4. | `DEFERRED_P9`; blocks external-target production publication, not P4 local workspace publication. |
| P4-ISSUE-012 | P2 | STEP 7 helper probe | Background lineage helper accepts claim generation zero while schema/SQL require at least one. | P4 executes IA only; record this as a mandatory P6 correction before CA/PA/EA execution. | `DEFERRED_P6`; no background execution in P4. |

## Extracted AgentExecution Vocabulary

The exact P4 state vocabulary extracted from Frozen Agent Doc 01 is:

```text
QUEUED
RUNNING
WAITING_INPUT
WAITING_CONFIRMATION
WAITING_APPROVAL
WAITING_DEPENDENCY
RECONCILIATION_REQUIRED
SUCCEEDED
FAILED
BLOCKED
ESCALATED
CANCELLED
```

The exact phase vocabulary is:

```text
INTAKE
BASE_CONTEXT
INTENT_RESOLUTION
CONTEXT_EXPANSION
PLAN_BUILD
PLAN_VALIDATE
PLAN_COMPILE
STEP_EXECUTION
RESULT_VERIFY
RESULT_SYNTHESIS
RESULT_PUBLISH
FINALIZE
```

P4 initially uses only the subset reached by the compatibility path, but its
physical model must not narrow or redefine the Frozen vocabulary.

## Gate Rule

STEP 9 may proceed with no open P0 issue. P4 feature implementation may begin
only after P4-ISSUE-002 and P4-ISSUE-003 have explicit source-backed decisions
and all P1 issues have a mapped Slice and acceptance test.
