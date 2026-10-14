# P6 NSL READ Integration Issue Register v1.1

**Status:** P6-S0 COMPLETE; P6-S1 NEXT

| ID | Sev | Issue | v1.1 Decision | Status |
|---|---:|---|---|---|
| P6-ISSUE-001 | P0 | Runtime is v0.1 while target is v0.2 | v0.2-compatible AE contract + explicit v0.1 backend adapter | DESIGN_CLOSED |
| P6-ISSUE-002 | P0 | READ BusinessOperationId vs P5 null rule | StepResult v1.2 schema fixes LOCAL_SKILL READ non-null BOI and null fingerprint | CONTRACT_CLOSED |
| P6-ISSUE-003 | P0 | Exact SkillExecutionRequest machine schema missing | Source-backed P6 schema and Golden example validated | CLOSED |
| P6-ISSUE-004 | P1 | NSLExecutionId ownership ambiguous | AE allocates/persists; NSL owns lifecycle semantics | DESIGN_CLOSED |
| P6-ISSUE-005 | P1 | P5 cannot execute LOCAL_SKILL | CA01 contract closed; S4 activates executor | OPEN_S4 |
| P6-ISSUE-006 | P1 | No production AE worker | S0 worker lifecycle/entrypoint closed; S1 composes DB dispatcher assignment source | FOUNDATION_CLOSED_S1_COMPOSITION |
| P6-ISSUE-007 | P1 | No tenant dispatcher | S1 single-leader bounded dispatcher | OPEN_S1 |
| P6-ISSUE-008 | P1 | Worker may claim unsupported executor | capability filter + lease CAS in one claim transaction | DESIGN_CLOSED_S1_IMPL |
| P6-ISSUE-009 | P1 | Dispatcher fairness authority ambiguous | one DB-protected active leader; restart rebuilds from DB | DESIGN_CLOSED_S1_IMPL |
| P6-ISSUE-010 | P1 | Backpressure semantics incomplete | bounded active claims/depth/batch; S1 fixes concrete error behavior | OPEN_S1 |
| P6-ISSUE-011 | P1 | VerifiedNspPackage != canonical VerifiedSkillArtifact | Exact gateway projection and evidence/ref boundary fixed | CONTRACT_CLOSED_S2_IMPL |
| P6-ISSUE-012 | P1 | v0.1 job lacks Agent/Plan/Step/BOI/correlation fields | Exhaustive adapter map and AE binding contract fixed | CONTRACT_CLOSED_S3_S5_IMPL |
| P6-ISSUE-013 | P1 | Full AgentContext copy risk | Bounded context projection schema and rejection rules fixed | CONTRACT_CLOSED_S3_IMPL |
| P6-ISSUE-014 | P1 | Exhaustive NSL status mapping missing | All eight v0.1 statuses mapped | CLOSED |
| P6-ISSUE-015 | P1 | Blind replay unsafe | no arbitrary Agent Runtime replay API | DESIGN_CLOSED |
| P6-ISSUE-016 | P2 | Process-isolation profile not selected | `NSL_V01_PROCESS_ISOLATED` selected; S5 implements adapter | CONTRACT_CLOSED_S5_IMPL |
| P6-ISSUE-017 | P2 | Golden READ fixture not selected | Exact signed `FINANCE.PROJECT_BUDGET_CHECK@1.0.0` fixture selected and executed | CLOSED |
| P6-ISSUE-018 | P1 | Timeline could overclaim historical state | deterministic projection; unknown optional history remains null | DESIGN_CLOSED_S6_IMPL |
| P6-ISSUE-019 | P1 | Old trace sees one job/step only | S6 complete retained-evidence timeline | OPEN_S6 |
| P6-ISSUE-020 | P0 | Exact NSL checkout must be verified in the Codex workspace | CA01 refreshed clean exact `803f22a...` checkout | CLOSED |
| P6-ISSUE-021 | P2 | v0.2 backend may arrive mid-P6 | backend port permits explicit swap; no auto-detection | RESOLVED_DESIGN |
| P6-ISSUE-022 | P2 | v0.1 AE-004/AE-008 external gaps | S7 closes dispatch/consume and result/explanation separation | OPEN_S7 |

## Gate

The P6-CA01 gate and P6-S0 worker foundation are closed. P6-S1 may begin;
dispatcher composition, fairness and capability-aware claim remain explicitly
open and are not claimed by the S0 lifecycle foundation.
