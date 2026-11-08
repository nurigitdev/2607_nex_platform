# P9-S17: AgentResult PRIMARY Admission

## Scope

`AeAgentResultSourceAdapter` now turns an authoritative completed AE
AgentResult into one primary WA WorkEvidence/WorkAsset admission.

- IA admits only project-neutral `PROMPT / WORKSPACE_RESULT_ACK` lineage.
- CA, PA, and EA require complete claimed-work lineage,
  `WC_WORK_RESULT_ACK`, and an EOS-verified active Project.
- Unknown authority profiles fail closed and require a controlled amendment.
- Results before the completion barrier return the retryable
  `WA_AGENT_RESULT_NOT_COMPLETE` error.
- Exact tenant, execution, result revision, and result hash matching is
  mandatory before any mutation.

The adapter reuses `WaEvidenceAdmissionService`; no parallel persistence path
or new table is introduced. WA outbound service tokens support TEST_MOCK,
DUAL_READ, and SIGNED_ONLY profiles for AE/EOS and later WC/OA adapters.

## Verification

Tests cover IA, CA, PA, EA, scheduler-style PA claimed work, incomplete results,
missing claim lineage, unknown agent type, identity/hash drift, Project denial,
missing Project verification, malformed source fields, HTTP failures, and token
profile admission.

- Focused regression: `75 passed`
- NeX-WA Slice Gate: `181 passed, 8 skipped`
- WA aggregate coverage: statement `98.25%`, branch `96.13%`
- New adapter and token resolver: statement `100%`, branch `100%`
- Ruff and repository diff hygiene: passed

Actual multi-service PostgreSQL and signed-token execution remains assigned to
P9-CA03 after P9-S20.
