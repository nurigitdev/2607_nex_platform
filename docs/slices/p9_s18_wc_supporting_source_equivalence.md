# P9-S18: WC SUPPORTING Resolution and Source Equivalence

## Scope

Background AgentResult admission now resolves the exact WC WorkResult by
AgentExecution and binds it as supporting evidence to the already authoritative
Agent work.

The boundary requires exact agreement for tenant, AgentExecution, WorkItem,
Claim, claim generation, Assignment, and submitted Agent. A semantic mismatch
fails closed. WC unavailability is retryable and does not admit partial work.

Persistence remains one Agent WorkAsset:

```text
AE AgentResult -> PRIMARY WorkEvidence
WC WorkResult  -> SUPPORTING WorkEvidence
both           -> one AGENT_EXECUTION_RESULT WorkAsset
```

`WaEvidenceAdmissionService` now admits an evidence set plus its asset in one
unit of work. This is a generalization of the existing local UoW, not a second
queue or table. Exact replay preserves one asset and two evidence facts.

## Verification

Tests cover source equivalence, all lineage mismatch fields, WC unavailable
then recovery, malformed revision/hash/time, missing client, HTTP transport,
atomic two-evidence admission, replay, and no double counting.

- Focused regression: `50 passed`
- NeX-WA Slice Gate: `200 passed, 8 skipped`
- WA aggregate coverage: statement `97.41%`, branch `94.41%`
- Changed AgentResult source adapter: statement `100%`, branch `100%`
- Ruff and repository diff hygiene: passed

Actual WC/AE/WA PostgreSQL and signed-token execution remains assigned to the
P9-CA03 protected gate after P9-S20.
