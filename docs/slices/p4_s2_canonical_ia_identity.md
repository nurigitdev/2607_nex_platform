# P4-S2 Canonical IA Identity

## Goal

Persist one server-managed, project-neutral Interactive Agent for each trusted
tenant/principal pair without creating a transition-only identity model.

## Decision

`ae_agent_identity` is the only AgentIdentity source of record and follows the
Frozen `AgentIdentity v2.1` contract. `ae_ia_principal_assignment` is only a
lookup mapping from a trusted principal to that identity.

Lazy provisioning executes in one transaction:

```text
load assignment
→ insert candidate canonical IA
→ compete for unique (tenant_id, principal_id) assignment
→ remove losing candidate
→ reload and validate the winner
```

An eligible runtime identity must be `IA`, `ACTIVE`, and have a null
`project_id`. Inactive assignments and ineligible identities fail closed.
The provisioning API deliberately has no caller-supplied `agent_id` parameter,
so browser identity is never authoritative.

## Scope

- added migration `2001_ae_agent_identity`;
- added canonical identity and principal-assignment persistence;
- added concurrency-safe lazy provisioning and typed failures;
- validated returned identities against the Frozen JSON Schema;
- retained Project, Enterprise OS, WC, PA, and AgentExecution outside this
  Slice.

## Verification

The P4-S2 Slice Gate covers idempotency, concurrent provisioning, Frozen schema
validation, inactive and wrong-type rejection, invalid input, persistence
failure, and migration constraints.

Result:

- AE Slice Gate: `2961 passed, 5 skipped`;
- overall coverage: statement `98.31%`, branch `96.20%`;
- `agent_identity.py`: statement `100.00%`, branch `100.00%`;
- contract validation: 174 schemas, 236 positive examples, 204 negative
  examples, and 7 OpenAPI documents.
