# P6 NSL READ Integration Issue Register v1.1

**Status:** P6-CA01A CONSOLIDATED PRE-IMPLEMENTATION REGISTER

| ID | Sev | Issue | v1.1 Decision | Status |
|---|---:|---|---|---|
| P6-ISSUE-001 | P0 | Runtime is v0.1 while target is v0.2 | v0.2-compatible AE contract + explicit v0.1 backend adapter | DESIGN_CLOSED |
| P6-ISSUE-002 | P0 | READ BusinessOperationId vs P5 null rule | StepResult semantic version 1.2; LOCAL_SKILL READ requires stable non-null BusinessOperationId | CA01_SCHEMA_REQUIRED |
| P6-ISSUE-003 | P0 | Exact SkillExecutionRequest machine schema missing | P6-CA01 must extract source-backed schema | BLOCKS_ALL_SLICES |
| P6-ISSUE-004 | P1 | NSLExecutionId ownership ambiguous | AE allocates/persists; NSL owns lifecycle semantics | DESIGN_CLOSED |
| P6-ISSUE-005 | P1 | P5 cannot execute LOCAL_SKILL | CA01 defines capability/artifact contract; S4 activates executor | OPEN_CA01 |
| P6-ISSUE-006 | P1 | No production AE worker | S0 after CA01 | OPEN_S0 |
| P6-ISSUE-007 | P1 | No tenant dispatcher | S1 single-leader bounded dispatcher | OPEN_S1 |
| P6-ISSUE-008 | P1 | Worker may claim unsupported executor | capability filter + lease CAS in one claim transaction | DESIGN_CLOSED_S1_IMPL |
| P6-ISSUE-009 | P1 | Dispatcher fairness authority ambiguous | one DB-protected active leader; restart rebuilds from DB | DESIGN_CLOSED_S1_IMPL |
| P6-ISSUE-010 | P1 | Backpressure semantics incomplete | bounded active claims/depth/batch; S1 fixes concrete error behavior | OPEN_S1 |
| P6-ISSUE-011 | P1 | VerifiedNspPackage != canonical VerifiedSkillArtifact | CA01 fixes projection | OPEN_CA01 |
| P6-ISSUE-012 | P1 | v0.1 job lacks Agent/Plan/Step/BOI/correlation fields | AE durable binding preserves canonical fields; adapter passes needed subset | OPEN_CA01 |
| P6-ISSUE-013 | P1 | Full AgentContext copy risk | explicit bounded projection contract | OPEN_CA01 |
| P6-ISSUE-014 | P1 | Exhaustive NSL status mapping missing | CA01 closes mapping | OPEN_CA01 |
| P6-ISSUE-015 | P1 | Blind replay unsafe | no arbitrary Agent Runtime replay API | DESIGN_CLOSED |
| P6-ISSUE-016 | P2 | Process-isolation profile not selected | CA01 selects and proves crash/timeout containment | OPEN_CA01 |
| P6-ISSUE-017 | P2 | Golden READ fixture not selected | CA01 selects exact signed READ fixture | OPEN_CA01 |
| P6-ISSUE-018 | P1 | Timeline could overclaim historical state | deterministic projection; unknown optional history remains null | DESIGN_CLOSED_S6_IMPL |
| P6-ISSUE-019 | P1 | Old trace sees one job/step only | S6 complete retained-evidence timeline | OPEN_S6 |
| P6-ISSUE-020 | P0 | Exact NSL checkout must be verified in the Codex workspace | Baseline checkout `803f22a...` is present and clean; CA01 must refresh SHA/state before closure | SOURCE_AVAILABLE_CA01_REFRESH_REQUIRED |
| P6-ISSUE-021 | P2 | v0.2 backend may arrive mid-P6 | backend port permits explicit swap; no auto-detection | RESOLVED_DESIGN |
| P6-ISSUE-022 | P2 | v0.1 AE-004/AE-008 external gaps | S7 closes dispatch/consume and result/explanation separation | OPEN_S7 |

## Gate

No P6 feature Slice starts until P6-ISSUE-003 and P6-ISSUE-020 are finally
closed through source-backed P6-CA01, together with all CA01-required machine
contracts. Baseline source availability alone does not close P6-CA01.
