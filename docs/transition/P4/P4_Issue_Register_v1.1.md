# P4 Agent Runtime Foundation Issue Register v1.1

**Status:** ACTIVE — ARCHITECTURE CLOSURE APPLIED
**Supersedes:** `P4_Issue_Register_v1.0.md`

| ID | Sev | Issue | v1.1 Decision | Status |
|---|---:|---|---|---|
| P4-ISSUE-001 | P1 | No standalone AgentExecution machine schema | Frozen Agent state/phase is authoritative; P4 defines physical persistence only. | RESOLVED_FOR_P4 |
| P4-ISSUE-002 | P1 | IA provisioning/resolution | Use canonical `ae_agent_identity`; add only principal→IA assignment. | RESOLVED_FOR_P4 |
| P4-ISSUE-003 | P0 | PROMPT requires project_id before Project resolution | P4-CA01: PROMPT+IA allows null; claimed work/PA still require Project. | CLOSED_BY_P4_CA01 |
| P4-ISSUE-004 | P1 | Publication ACK needs current authority evidence | AgentResult implemented; workspace delivery stays PENDING; no SUCCEEDED. | BOUNDED_DEFERRED |
| P4-ISSUE-005 | P1 | Complete AgentResult persistence | Implement complete envelope plus normalized columns. | RESOLVED_DESIGN |
| P4-ISSUE-006 | P1 | Result/delivery atomicity | Persist AgentResult + required PENDING delivery atomically. | RESOLVED_P4_BOUNDARY |
| P4-ISSUE-007 | P1 | Empty delivery collection can appear complete | SUCCEEDED prohibited in P4. | RESOLVED_DESIGN |
| P4-ISSUE-008 | P1 | result_hash algorithm | Use canonical JSON/SHA-256 semantic projection with fixed vectors. | RESOLVED_DESIGN |
| P4-ISSUE-009 | P3 | SRS rollout section typo | Corrected in v1.1. | CLOSED |
| P4-ISSUE-010 | P3 | historical v1 tag record | 00A addendum remains tag verification authority. | CLOSED |
| P4-ISSUE-011 | P2 | publication reconciliation storage | Deferred. | DEFERRED |
| P4-ISSUE-012 | P2 | background claim-generation mismatch | Out of P4. | DEFERRED_P6 |
| P4-ISSUE-013 | P1 | OA lacks full publication preflight authority | ACK/preflight deferred; no fake evidence. | BOUNDED_DEFERRED |
| P4-ISSUE-014 | P1 | async CX terminalizes after initial request | Use canonical CONTINUE_EXECUTION RuntimeJob; never replay generation. | RESOLVED_FOR_P4 |
| P4-ISSUE-015 | P2 | service_jobs is not canonical AE runtime queue | Use Frozen `ae_runtime_job` / `ae_runtime_job_attempt`. | RESOLVED_FOR_P4 |
| P4-ISSUE-016 | P1 | Workspace 1:1 chat document | Keep Workspace 1:N Conversation; retain legacy pointer. | RESOLVED_FOR_P4 |
| P4-ISSUE-017 | P1 | MOCK_ENTERPRISE_OS in old plan | Removed. | CLOSED |
| P4-ISSUE-018 | P1 | mutable interaction table cannot restore append-only history | Add Conversation Message/Event journal; keep interaction projection. | RESOLVED_FOR_P4 |
| P4-ISSUE-019 | P1 | Conversation-to-Project binding | Conversation has no Project binding. | CLOSED |
| P4-ISSUE-020 | P1 | IAChatRun parallel runtime | Removed by DEC-01/07. | CLOSED |
| P4-ISSUE-021 | P1 | append-only history | Implement journal, not Agent Memory. | RESOLVED_FOR_P4 |
| P4-ISSUE-022 | P1 | PERSONAL scope invented to avoid Project | Remove product concept; use tenant/principal ownership plus nullable project trigger. | CLOSED |
| P4-ISSUE-023 | P1 | Weekly Digest scope creep | Remove from P4. | CLOSED |
| P4-ISSUE-024 | P1 | new IA per login/prompt | persistent canonical IA + assignment; login does not mint IA. | RESOLVED_FOR_P4 |
| P4-ISSUE-025 | P1 | cannot reach SUCCEEDED without ACK | End P4 at AgentResult + PENDING delivery / RESULT_PUBLISH phase. | RESOLVED_P4_BOUNDARY |
| P4-ISSUE-026 | P1 | Exact pre-terminal AgentExecution state for BLOCKED/FAILED/CANCELLED AgentResult is not explicit in the P4 baseline. | Success-capable results remain `RUNNING / RESULT_PUBLISH` until required ACK. `BLOCKED`, `FAILED`, and `CANCELLED` results transition directly to the matching terminal execution state with `FINALIZE`; their PENDING workspace delivery remains durable but is not a success barrier. See the P4-S7 state-mapping closure. | CLOSED_BY_P4_S7_STATE_MAPPING |

## Frozen AgentExecution Reference

States:

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

Phases:

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

## Gate

Open P0:

```text
none
```

P4-CA01 closed on 2026-10-13 with focused E1/E2E-01 contract-impact probes,
manifest verification, and a re-freeze addendum. Canonical P4 PROMPT source
implementation may begin.

P4-ISSUE-026 closed before P4-S7 source implementation. The cited Frozen
evidence and exact mapping are recorded in
`P4_ISSUE_026_AgentResult_State_Mapping_Closure_v1.0.md`; P4-S7 verifies every
AgentResult status with state-transition tests.
