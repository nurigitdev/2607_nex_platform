# P6 NSL READ Integration Issue Register v1.1

**Status:** P6-S3 COMPLETE; P6-S4 NEXT

| ID | Sev | Issue | v1.1 Decision | Status |
|---|---:|---|---|---|
| P6-ISSUE-001 | P0 | Runtime is v0.1 while target is v0.2 | v0.2-compatible AE contract + explicit v0.1 backend adapter | DESIGN_CLOSED |
| P6-ISSUE-002 | P0 | READ BusinessOperationId vs P5 null rule | StepResult v1.2 schema fixes LOCAL_SKILL READ non-null BOI and null fingerprint | CONTRACT_CLOSED |
| P6-ISSUE-003 | P0 | Exact SkillExecutionRequest machine schema missing | Source-backed P6 schema and Golden example validated | CLOSED |
| P6-ISSUE-004 | P1 | NSLExecutionId ownership ambiguous | AE allocates/persists; NSL owns lifecycle semantics | DESIGN_CLOSED |
| P6-ISSUE-005 | P1 | P5 cannot execute LOCAL_SKILL | CA01 contract closed; S4 activates executor | OPEN_S4 |
| P6-ISSUE-006 | P1 | No production AE worker | S0 lifecycle plus S1 DB dispatcher assignment source; execution handler remains S4 | FOUNDATION_CLOSED |
| P6-ISSUE-007 | P1 | No tenant dispatcher | S1 DB-leased, fenced, bounded dispatcher | CLOSED |
| P6-ISSUE-008 | P1 | Worker may claim unsupported executor | capability filter + lease CAS in one transaction | CLOSED |
| P6-ISSUE-009 | P1 | Dispatcher fairness authority ambiguous | one DB-protected leader; each round rebuilds from durable state | CLOSED |
| P6-ISSUE-010 | P1 | Backpressure semantics incomplete | active/depth/batch caps plus explicit retryable DELAY/REJECT errors | CLOSED |
| P6-ISSUE-011 | P1 | VerifiedNspPackage != canonical VerifiedSkillArtifact | Exact gateway projection, current governance admission, and bounded persistence implemented | CLOSED |
| P6-ISSUE-012 | P1 | v0.1 job lacks Agent/Plan/Step/BOI/correlation fields | Durable AE binding/request implemented; S5 maps the bounded request to v0.1 | BINDING_CLOSED_S5_ADAPTER |
| P6-ISSUE-013 | P1 | Full AgentContext copy risk | Bounded projection persistence and recursive private-material rejection implemented | CLOSED |
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

The P6-CA01 gate and P6-S0 through P6-S3 foundations are closed. P6-S4 may
begin. `LOCAL_SKILL` execution remains fail-closed until that Slice verifies
and registers the complete executor dependency set.
