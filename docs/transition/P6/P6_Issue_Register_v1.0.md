# P6 NSL READ Integration Issue Register v1.0

**Status:** ACTIVE PRE-IMPLEMENTATION REGISTER

| ID | Sev | Issue | Decision / Required Action | Status |
|---|---:|---|---|---|
| P6-ISSUE-001 | P0 | Actual NSL runtime is v0.1 while Frozen target is v0.2 | Use v0.2-compatible AE contract with explicit v0.1 backend adapter. | DESIGN_DECIDED |
| P6-ISSUE-002 | P0 | Frozen request requires BusinessOperationId for READ; P5 StepResult forced it null | P6-CA01 controlled transition contract: LOCAL_SKILL READ uses stable non-null BusinessOperationId; operation_fingerprint remains null. | BLOCKS_S2_PLUS |
| P6-ISSUE-003 | P0 | Exact SkillExecutionRequest machine shape not yet extracted for P6 | P6-CA01 shall produce transition schema and adapter map. | BLOCKS_S2_PLUS |
| P6-ISSUE-004 | P1 | v0.1 `execution_id` could be confused with AgentExecutionId | P6 NSLExecutionId is distinct and maps to v0.1 execution_id. | DESIGN_DECIDED |
| P6-ISSUE-005 | P1 | P5 capability snapshot cannot currently execute LOCAL_SKILL | Extend capability/executable contract under P6; exact Skill binding required. | OPEN_CA01 |
| P6-ISSUE-006 | P1 | P5 has no continuously running production AE worker | P6-S0 dedicated worker process. | OPEN_S0 |
| P6-ISSUE-007 | P1 | RuntimeJob claim is tenant-specific with no dispatcher | P6-S1 bounded round-robin tenant dispatcher. | OPEN_S1 |
| P6-ISSUE-008 | P1 | P4/P5 trace assumes one job/compatibility step in old projection | P6 complete execution timeline projection. | OPEN_S6 |
| P6-ISSUE-009 | P1 | v0.1 VerifiedNspPackage != Frozen VerifiedSkillArtifact shape | P6 Skill Artifact Gateway projects verified package evidence into canonical P6 artifact shape. | OPEN_CA01 |
| P6-ISSUE-010 | P1 | v0.1 SkillExecutionJob lacks Agent/Plan/Step IDs, BusinessOperationId, correlation/causation | Keep in canonical P6 wrapper/ledger; adapter passes only fields v0.1 needs. | OPEN_CA01 |
| P6-ISSUE-011 | P1 | Whole AgentContext could be copied into v0.1 runtime_context | Prohibit; define typed bounded context projection schema. | OPEN_CA01 |
| P6-ISSUE-012 | P1 | NSL result status mapping is not frozen at P6 StepResult level | P6-CA01 closes complete mapping. | OPEN_CA01 |
| P6-ISSUE-013 | P1 | Generic operator replay could be unsafe later for WRITE | No arbitrary replay API; controlled retry only. | DESIGN_DECIDED |
| P6-ISSUE-014 | P2 | Production process-isolation profile not selected | P6-CA01 decides in-process worker vs process-isolated backend profile; crash containment required. | OPEN_CA01 |
| P6-ISSUE-015 | P2 | Golden READ Skill/Tool for E2E not selected | Select one exact signed NSP READ fixture and deterministic/production-like READ Tool adapter. | OPEN_CA01 |
| P6-ISSUE-016 | P2 | v0.1 NSL-AE-004 and AE-008 were conditional external gaps | P6 E2E shall close actual dispatch/consume and result/explanation separation evidence. | OPEN_S7 |
| P6-ISSUE-017 | P2 | Tenant fairness defaults not fixed | Defaults are deployment config; semantic policy is bounded round-robin + per/global caps. | BOUNDED |
| P6-ISSUE-018 | P2 | NSL v0.2 Track may become available during P6 | Backend port allows swap; acceptance reruns unchanged AE-facing tests. | RESOLVED_DESIGN |

## Entry Rule

P6-S0/S1 may proceed after this document set is accepted.

P6-S2 and later MUST wait for P6-CA01 closure of P0 contract issues.
