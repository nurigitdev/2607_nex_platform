# P5 Agent Planning & Execution Foundation Issue Register v1.1

**Status:** P5-CA01A DESIGN CLOSURE COMPLETE / IMPLEMENTATION EVIDENCE PENDING

**Supersedes:** P5 Issue Register v1.0

| ID | Severity | Issue | v1.1 decision | Status |
|---|---:|---|---|---|
| P5-ISSUE-001 | P1 | Legacy reference schemas are not final P5 machine authority | Use reviewed P5 v1.1 transition contracts; Frozen semantics win. | CLOSED_CA01 |
| P5-ISSUE-002 | P1 | P4 executable-step schema is one-step compatibility-only | P5-S5 performs historical-row-safe multi-step generalization. | CLOSED_DESIGN |
| P5-ISSUE-003 | P1 | Capability catalog missing | Tenant-scoped immutable exact-version snapshot. | CLOSED_DESIGN |
| P5-ISSUE-004 | P1 | Existing IntentDecision is not WorkIntent | P5-S1 deterministic adapter. | CLOSED_DESIGN |
| P5-ISSUE-005 | P1 | RuntimePolicy may overlap Planner authority | RuntimePolicy is bounded input; Planner/Validator remain separate. | CLOSED_DESIGN |
| P5-ISSUE-006 | P1 | Clarification resume not fixed | Persist WAITING_INPUT; resume deferred. | CLOSED_DESIGN |
| P5-ISSUE-007 | P1 | P4 AgentResult assumes one compatibility step | Move finalization to plan terminalization. | CLOSED_DESIGN |
| P5-ISSUE-008 | P1 | START/CONTINUE only | Sufficient for P5; no resume job added. | CLOSED_DESIGN |
| P5-ISSUE-009 | P1 | Exact executable type vocabulary | Fixed by CA01; availability is scope-guarded. | CLOSED_CA01 |
| P5-ISSUE-010 | P1 | LOCAL_SKILL visible before P6 | Reject as `EXECUTOR_NOT_AVAILABLE`; zero NSL calls. | RESOLVED_DESIGN |
| P5-ISSUE-011 | P2 | Parallel DAG complexity | DAG represented; serial-ready execution. | RESOLVED_DESIGN |
| P5-ISSUE-012 | P2 | LLM planner destabilization | Deterministic templates mandatory; LLM optional/shadow. | RESOLVED_DESIGN |
| P5-ISSUE-013 | P2 | Capability IDs not public/stable | Initial IDs remain internal. | CLOSED_CA01 |
| P5-ISSUE-014 | P2 | Historical P4 rows lack P5 fields | Nullable-for-history; new P5 rows domain-required. | RESOLVED_DESIGN |
| P5-ISSUE-015 | P2 | Required ResultDelivery remains PENDING | Preserve no-false-SUCCEEDED boundary. | RESOLVED |
| P5-ISSUE-016 | P2 | Enterprise entity resolution incomplete | Trusted resolver port; unresolved required values wait/block. | RESOLVED_DESIGN |
| P5-ISSUE-017 | P1 | Prompt version writes mutate same version | Immutable insert-or-verify in S1. | CLOSED_DESIGN |
| P5-ISSUE-018 | P1 | Prompt Registry acceptance too broad | Mandatory only for enabled LLM stages; deterministic P5 can close without LLM planner. | CLOSED_CA01 |
| P5-ISSUE-019 | P2 | P5 semantic hash profile inconsistent | Canonical semantic `sha256:` profile fixed. | CLOSED_CA01 |
| P5-ISSUE-020 | P2 | Future vocabulary may be mistaken for runtime availability | Scope guards explicitly reject future paths. | CLOSED_CA01 |
| P5-ISSUE-021 | P1 | P5 ExecutablePlan treated `E1` as `ExecutableStepId`, conflicting with P4 UUID | `E1` becomes `CompiledStepKey`; Runtime `ExecutableStepId` remains UUID. | CLOSED_CA01A |
| P5-ISSUE-022 | P1 | Existing bare SHA-256 digests conflict with prefixed P5 semantic hashes | Explicit dual representation + centralized conversion utility. | CLOSED_CA01A |
| P5-ISSUE-023 | P1 | PlanValidation status lacked deterministic runtime mapping | Exact status→directive→state→phase matrix fixed; `max_auto_replan=0`. | CLOSED_CA01A |
| P5-ISSUE-024 | P1 | StepResult future WRITE fields could be accidentally populated | Both fields required and `const:null` in P5 v1.1 schema. | CLOSED_CA01A |
| P5-ISSUE-025 | P1 | Prompt binding pointer could update without durable history | History insert + pointer update atomic with lock/CAS. | CLOSED_CA01A |
| P5-ISSUE-026 | P2 | Runtime UUID could make ExecutablePlan hash nondeterministic | Semantic hash excludes UUID and uses `CompiledStepKey`. | CLOSED_CA01A |

## Implementation gate

There are no open P0/P1 **design** decisions after P5-CA01A.

`CLOSED_DESIGN`, `CLOSED_CA01`, and `CLOSED_CA01A` still require owning-slice implementation/test evidence.
