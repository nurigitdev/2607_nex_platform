# P4-ISSUE-026 AgentResult State Mapping Closure v1.0

**Status:** CLOSED BEFORE P4-S7 SOURCE IMPLEMENTATION  
**Date:** 2026-10-13

## Decision

P4 uses the following deterministic mapping after an immutable AgentResult and
its required `WORKSPACE_RESULT` delivery are created atomically:

| AgentResult status | AgentExecution state | AgentExecution phase | completed_at |
|---|---|---|---|
| `SUCCEEDED` | `RUNNING` | `RESULT_PUBLISH` | null |
| `PARTIAL` | `RUNNING` | `RESULT_PUBLISH` | null |
| `BLOCKED` | `BLOCKED` | `FINALIZE` | result creation time |
| `FAILED` | `FAILED` | `FINALIZE` | result creation time |
| `CANCELLED` | `CANCELLED` | `FINALIZE` | result creation time |

Every row still receives exactly one required PENDING workspace delivery. The
delivery is a success-completion barrier only for a success-capable result. It
does not turn a failed, blocked, or cancelled execution back into `RUNNING`.

## Frozen Evidence

The decision is derived from these unchanged Frozen documents:

1. `01_NeX_Unified_Agent_Loop_and_AgentExecution_State_Machine_v0.3_final_consistency_closure_v1.1.docx`
   - State model section: `BLOCKED` is explicitly terminal in v1.
   - Terminal transition rule: terminal transitions use `FINALIZE` or retain
     the last meaningful phase and record `completed_at`.
   - Transition table T12/T13/T15 maps `FAIL`, `BLOCK`, and `CANCEL` directly to
     `FAILED`, `BLOCKED`, and `CANCELLED`.
2. `08_NeX_Result_Verification_Aggregation_Presentation_v0.2_final_consistency_closure_v1.1.docx`
   - Result-processing matrix: verified results with required deliveries
     pending use `RESULT_PUBLISH / YIELD`; all required ACKs permit
     `FINALIZE -> SUCCEEDED`.
   - A required criterion failure maps directly to `FAILED`.
   - Finalization model lists `FINALIZE` with terminal states `SUCCEEDED`,
     `FAILED`, `BLOCKED`, `ESCALATED`, and `CANCELLED`.
   - `RES-FR-082` prohibits `SUCCEEDED` while a required delivery is not ACKed;
     it does not prohibit the other terminal states.

## P4 Boundary

P4 does not execute publication, preflight, ACK, retry, or reconciliation.
Therefore:

- `SUCCEEDED` and `PARTIAL` AgentResult rows stop at the Frozen pre-success
  handoff `RUNNING / RESULT_PUBLISH`;
- non-success outcomes preserve their authoritative terminal meaning;
- no P4 code may infer `SUCCEEDED` from legacy Chat `COMPLETED` alone;
- no delivery state may replay retrieval or generation.

This closure resolves `P4-ISSUE-026` without modifying a Frozen artifact.
