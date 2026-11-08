# P8-S26 Nested Delegation Parent Claim Authority

## Scope

Admit a nested DelegationSpec `1.1` only while its parent Claim, Assignment,
delegating Agent, lease, generation, and AE AgentExecution acknowledgement are
all current.

## Runtime Boundary

- DelegationSpec `1.0` remains the first-level compatibility contract.
- DelegationSpec `1.1` requires the complete parent Claim tuple.
- AE handoff delivery records the returned AgentExecution identity on the
  existing `wc_assignment` row.
- Nested admission locks the parent Claim and Assignment before inserting the
  child WorkItem and immutable lineage in the same transaction.
- stale, expired, reclaimed, mismatched, or unacknowledged parent authority
  returns `wc.delegation_parent_authority_stale` and creates zero child state.
- the nested requester must be the exact delegating Agent.

## Storage

No second P8.2A table was introduced. Migration
`1005_wc_assignment_execution` extends the existing `wc_assignment` relation
with a nullable, tenant-unique `agent_execution_id`. The sole new Delegation
Guard relation remains `wc_delegation_lineage`.

## Verification

- P8-S24..S26 focused regression: `50 passed`
- P7/WC compatibility regression: `324 passed, 8 protected skips`
- bounded four-module statement coverage: `90.80%`
- bounded four-module branch coverage: `85.53%`
- migration inventory assertion is derived from the repository contents
- Python compile and whitespace validation: pass

Actual PostgreSQL migration and protected acceptance remain scheduled for
P8-S31. P8-S28 and P8-S29 add the requested focused PostgreSQL concurrency
evidence before that final gate. The repository-wide Full Gate, whose latest
baseline is above both coverage thresholds, is intentionally deferred to S31.
