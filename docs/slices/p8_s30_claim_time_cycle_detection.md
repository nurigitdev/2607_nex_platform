# P8-S30 Claim-Time Cycle Detection

## Scope

Reject a routed claimant when the selected Agent already appears in the
current WorkItem's immutable delegation ancestor chain.

## Claim Boundary

- cycle detection runs after routing has selected and revalidated the actual
  candidate, inside `commit_claim`
- the current lineage row and every parent lineage row through the root are
  evaluated in current-to-root order
- Agent identity is the exact `(agent_id, agent_type)` pair
- PostgreSQL traversal uses a bounded recursive CTE over the existing
  `wc_delegation_lineage`; no new relation or migration is introduced
- an incomplete, cyclic, or structurally inconsistent lineage fails closed as
  `wc.delegation_lineage_invalid`
- an ancestor candidate fails as `wc.delegation_cycle_detected`
- historical P7 WorkItems without delegation lineage remain claimable
- denial occurs before Claim, Assignment, handoff outbox, or AgentExecution
  authority is created

## Compatibility Adjustments

- the S27 depth-ten fixture now provides its complete ten-row ancestor chain
- the S29 root-budget tree now uses distinct PA identities by depth, preserving
  a non-cyclic 49-descendant concurrency fixture

These changes make the historical tests describe valid delegation state under
the newly activated cycle contract rather than weakening the guard.

## Verification

- S30 focused cycle, non-cycle, historical, malformed-lineage, and SQL
  projection tests: `4 passed`
- focused P8.2A regression: `61 passed`, `2 protected skips`
- S29 actual `nex_wc_test` cross-parent concurrency recheck after cycle
  activation: `4 passed`
- WC-related regression with the actual WC test database available:
  `304 passed`, `7 protected skips`
- contract validation: PASS

The repository-wide P8-S27 Checkpoint baseline remains statement `98.71%`
and branch `97.17%`. P8-S31 retains the actual PostgreSQL protected delegation
acceptance and mandatory Full Gate.
