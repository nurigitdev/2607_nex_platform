# Batch 02 CP02/CP06 Contract Delta

Normative targets introduced by this controlled batch:

- AE `AgentIdentity v2.1` and `AgentSession v2.1`
- WC `WorkItem v2.1`, `RoutingDecision v2.1`, generic `AGENT + agent_type(CA/PA/EA)`
- OA `EffectiveAuthorityContext v2.1`, `AuthorizationDecision v2.1` with explicit `tenant_id` and generic Agent identity

These files are delta contracts for Platform v2.1 and do not yet replace later CP03/CP04/CP05 contracts.


## E1 Contract Hardening v1.2

Final Authority / Identity hardening adds:

- PA `project_id` must be non-null.
- Routing candidate `candidate_type=AGENT` requires `agent_type=CA|PA|EA`.
- `WC ClaimExecutionHandoff v2.1` → `AE ExecutionTrigger v2.1` is the machine-readable background execution bridge.
- AE Agent Registry DB/service contract enforces at most one ACTIVE PA per `(tenant_id, project_id)`.

These are contract-strengthening changes only; Agent v2.1 / NSL v0.2 semantic authority is unchanged.


## Step2 E2E Contract Hardening v1.3

- WorkItem routing supports `required_agent_type = CA | PA | EA`. PA-targeted work requires project scope/reference.
- RoutingDecision carries `required_agent_type`; eligible AGENT candidates must match it.
- Added normative `WorkResult v2.1` and `WORK_RESULT_SUBMITTED Event v2.1` with TenantId, source execution and current claim lineage.
- Parent dependency resumes from the deduplicated `WORK_RESULT_SUBMITTED` event after result-contract validation, never from Claim/Assignment.
