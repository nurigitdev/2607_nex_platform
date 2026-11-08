# PLAT-CP09 CX Context / Evidence Contracts

Platform v2.1 alignment rules:

- TenantId is explicit and separate from OrgScope / ProjectScope.
- CX remains the authoritative retrieval/evidence service; it does not own AgentContext.
- `CXEvidenceContext v2.1` is a bounded input to the AE Agent Context Builder.
- PA reuses project_scope and current OA authority; no PA-specific CX database/index is introduced.
- Tenant mismatch is fail-closed in ingestion/retrieval/cache/evidence/context access.
- AgentContext or CX Evidence Context must not be copied wholesale into NSL runtime_context.
