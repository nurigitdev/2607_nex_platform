# P5 Agent Planning & Execution Foundation Issue Register v1.0

**Status:** P5-CA01 DESIGN CLOSURE COMPLETE / IMPLEMENTATION EVIDENCE PENDING

| ID | Severity | Issue | Decision / Required Action | Status |
|---|---:|---|---|---|
| P5-ISSUE-001 | P1 | WorkIntent/AgentPlan/PlanStep machine schemas in repo are legacy reference, not final normative | P5-CA01 extracted reviewed transition contracts under `docs/transition/P5/contracts/`; Frozen semantics win on conflict. | CLOSED_CA01 |
| P5-ISSUE-002 | P1 | P4 `ae_executable_step` permits only `P4_CHAT_RAG_COMPATIBILITY` and one step per kind/execution | CA01-DEC-14 fixes an additive historical-row-safe migration; DDL and dual-dialect evidence belong to P5-S5. | CLOSED_DESIGN |
| P5-ISSUE-003 | P1 | No canonical P5 capability catalog implementation exists | CA01-DEC-04/17 fix a tenant-scoped immutable snapshot, exact binding, no implicit latest, and initial internal IDs. | CLOSED_DESIGN |
| P5-ISSUE-004 | P1 | Current `intent_policy.py` returns v1 IntentDecision, not Frozen WorkIntent | P5-S1 implements the deterministic adapter into the CA01 WorkIntent contract before required mode. | CLOSED_DESIGN |
| P5-ISSUE-005 | P1 | Current `runtime_policy.py` overlaps planning policy concerns | RuntimePolicy is an immutable bounded context/profile input; Plan Builder/Validator remain separate authorities. | CLOSED_DESIGN |
| P5-ISSUE-006 | P1 | Clarification resume API is not fixed by P4 | P5 persists explicit WAITING_INPUT/questions with zero side effects; resume/re-intent and RESUME_EXECUTION are deferred. | CLOSED_DESIGN |
| P5-ISSUE-007 | P1 | P4 AgentResult creation assumes one compatibility step | Final AgentResult moves to plan terminalization; disabled mode preserves P4 behavior. | CLOSED_DESIGN |
| P5-ISSUE-008 | P1 | P4 RuntimeJob DB only permits START_EXECUTION/CONTINUE_EXECUTION | P5 uses these for planning/step progression and explicitly defers clarification resume; no new job type is needed in P5. | CLOSED_DESIGN |
| P5-ISSUE-009 | P1 | Exact executable-step kind vocabulary must match Frozen Agent Doc 05/06 | CA01-DEC-09 fixes seven Frozen executable types and separates them from internal `executor_kind`. | CLOSED_CA01 |
| P5-ISSUE-010 | P1 | LOCAL_SKILL capability may appear before P6 executor exists | Compiler/scheduler must fail closed as unavailable; zero NSL calls in P5. | RESOLVED_DESIGN |
| P5-ISSUE-011 | P2 | Parallel DAG execution adds concurrency/idempotency complexity | Represent DAG but execute deterministic serial-ready order in P5 closure. | RESOLVED_DESIGN |
| P5-ISSUE-012 | P2 | LLM Plan Builder could destabilize first planning baseline | Deterministic/template plan is mandatory; LLM planner optional/shadow only. | RESOLVED_DESIGN |
| P5-ISSUE-013 | P2 | Capability IDs are not yet stable external vocabulary | `AE.CHAT.COMPATIBILITY` and `AE.RESULT.REPORT` are fixed as internal P5 IDs and remain non-public. | CLOSED_CA01 |
| P5-ISSUE-014 | P2 | Historical P4 rows lack plan/context references | New P5 columns may be nullable for historical rows; new P5 executions enforce non-null in application/domain. | RESOLVED_DESIGN |
| P5-ISSUE-015 | P2 | P4 ResultDelivery remains PENDING, so canonical SUCCEEDED remains blocked | Preserve P4 completion boundary. | RESOLVED |
| P5-ISSUE-016 | P2 | Entity resolution for enterprise Project/business objects is not fully implemented | Use trusted resolver ports; unresolved required selectors cause WAITING_INPUT, never fake IDs. | RESOLVED_DESIGN |
| P5-ISSUE-017 | P1 | Existing prompt version persistence mutates a version on conflict | P5-S1 changes version writes to immutable insert-or-verify and rejects hash/content drift. | CLOSED_DESIGN |
| P5-ISSUE-018 | P1 | Prompt Registry acceptance was broader than deterministic P5 slice ownership | Registry is mandatory for enabled LLM stages; optional LLM intent/dynamic planning remain disabled by default. | CLOSED_CA01 |
| P5-ISSUE-019 | P2 | P5 envelope hash projections were not uniform | CA01-DEC-11 fixes canonical JSON, SHA-256 representation, and semantic projection exclusions. | CLOSED_CA01 |
| P5-ISSUE-020 | P2 | Frozen full-agent vocabulary could be mistaken for P5 runtime availability | Transition schemas may expose reserved vocabulary, while P5 scope guards reject WC, NSL, WRITE, and background-agent paths. | CLOSED_CA01 |

## Pre-Implementation Gate

P5-CA01 supplied concrete decisions for P5-ISSUE-001, 002, 003, 004, 005,
006, 007, 009, 013, 017, 018, 019, and 020. The design entry gate is closed.

`CLOSED_DESIGN` and `CLOSED_CA01` do not claim source implementation. Each
decision still requires owning-slice tests, migration evidence, and regression
evidence before it can be considered implemented.
