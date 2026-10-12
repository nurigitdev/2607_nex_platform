# E2E Step2 Contract Hardening Amendment v1.3

**Status:** APPLIED — closes E2E01-P1-01, E2E04-PCG-01, E2E05-PCG-01.

Changes:
- SkillExecutionRequest v2.1 requires principal_context_ref + data_policy_ref and deterministic Frozen NSL security-context resolution.
- WorkResult v2.1 + WORK_RESULT_SUBMITTED Event v2.1 promoted to the normative WC contract pack with TenantId and Agent claim lineage.
- WorkItem/RoutingDecision/RoutingContext support required_agent_type. PA-targeted work requires project scope/reference and only PA candidates may satisfy the routing constraint.
- Exact requirements back-propagated into 04 / 14 / 15 / 29 / 31.

Frozen Agent v2.1 / NSL v0.2 semantics are unchanged.
