# P7-CA01 WC and Background Agent Transition Contracts

**Status:** SOURCE-BACKED CONTRACT BASELINE
**Scope:** P7 Work Coordination and CA/PA/EA background execution

## Contract Set

The following five files are byte-for-byte extracts of the Frozen v2.1 WC
machine contracts. Their filenames are transition-local; their `$id` values and
contents remain Frozen-owned.

```text
p7-work-item-v2.1.schema.json
p7-routing-decision-v2.1.schema.json
p7-claim-execution-handoff-v2.1.schema.json
p7-work-result-v2.1.schema.json
p7-work-result-submitted-v2.1.schema.json
```

P7 adds four implementation-facing transition contracts:

```text
p7-delegation-spec-v1.schema.json
p7-wait-registration-v1.schema.json
p7-plan-candidate-v1.schema.json
p7-claimed-work-planning-envelope-v1.schema.json
```

`DelegationSpec` carries semantic work requirements only. It cannot carry an
actual assignee, Claim, Assignment, lease, OA authorization decision, or
execution identity allocated by WC/AE.

`WaitRegistration` is AE-owned durable dependency state. It does not replace a
WC WorkItem or the AE RuntimeJob that eventually resumes execution.

`PlanCandidate` is the admitted planning candidate boundary used by the P7
claimed-work planning source. It does not grant routing, claim, assignment, or
execution authority.

`ClaimedWorkPlanningEnvelope` transports the byte-for-byte Frozen
`ClaimExecutionHandoff` beside a bounded WorkItem planning projection. The
projection supplies planning input only; the Frozen handoff remains the sole
claim and assignment authority and is not extended with P7-local fields.

## Initial Runtime Profile

Frozen-visible vocabulary remains intact, while P7 initially activates only:

```text
source_type      = AGENT_PLAN_STEP
candidate_type   = AGENT
agent_type       = CA | PA | EA
handoff          = committed Claim + Assignment only
result submitter = AGENT
```

`ACKNOWLEDGED`, HUMAN, EXTERNAL_AGENT, SCHEDULE, and recurring work remain
schema-visible but runtime-disabled. Their presence in a Frozen contract does
not authorize an initial P7 transition.

## Technical Job Reuse

These domain contracts are not common jobs. WC technical delivery, retry,
dead-letter, replay, heartbeat, and job-control mechanics reuse
`services/_shared/nex_runtime` and `common_job.v1`. The durable WC outbox remains
the event source of record; an idempotent bridge creates a common delivery job
from an outbox row.

## Fixtures

`examples/` contains one coherent PA delegation lineage. `tests/negative/`
contains fail-closed examples for project scope, agent type, lineage, authority
fields, and wait/resume identity.
