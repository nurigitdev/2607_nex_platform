# P8-S70: EOS ApprovalInstance / Stage Persistence

## Status

Completed on 2026-10-23.

## Scope

NeX-EOS now owns durable, tenant-scoped formal approval runtime state derived
from the exact P8-S69 policy selected for a protected business operation. This
Slice adds:

- `eos_approval_instance` for the immutable policy, operation, payload, write
  intent, requester, organization, Project, expiry, and lineage binding;
- `eos_approval_stage` for the copied ordered stage definition and current
  stage state;
- `eos_approval_decision` as the append-oriented decision-history storage and
  read model required by the later WC decision-ingress Slice;
- `SqlAlchemyEosApprovalInstanceRepository` for create-or-get, exact replay,
  tenant-scoped readback, active-stage lookup, and decision-history lookup;
- EOS dependency-container and application-state wiring;
- migration `2510_eos_approval_instance`.

P8-S70 does not project WC work, admit a human decision, advance stages, or
issue final ApprovalProof. P8-S71 owns WC projection and P8-S73 owns the
transactional decision append and state transition.

## Immutable Snapshot

Creation accepts an exact `approval_policy_id`; it does not resolve a policy
again from mutable selectors. The repository requires the policy to be active,
effective, and `BUSINESS_FORMAL`, then copies:

```text
policy ID + version + policy hash + ordered stages
```

The runtime binding also fixes:

```text
BusinessOperationId + operation + protected operation ref
+ PayloadHash + WriteIntentHash
+ requester + OrgUnit + Project
+ correlation/causation + optional expiry
```

The protected EOS business operation must already be `COMMITTED`, and its
payload hash must equal the requested approval payload hash. OrgUnit and
Project references must be active in the same tenant. The first stage starts as
`ACTIVE`; all later stages start as `WAITING`. Stage IDs are deterministically
derived from the ApprovalInstance ID and stage order.

Later policy changes cannot alter an existing instance. Exact idempotency
replay returns the original persisted snapshot, while any change to the
immutable request under the same idempotency key fails with
`EOS_APPROVAL_INSTANCE_REPLAY_CONFLICT`.

## Persistence Safety

- All ApprovalInstance, ApprovalStage, and ApprovalDecision identities are
  tenant scoped.
- A partial unique index permits at most one `ACTIVE` stage per instance.
- Composite foreign keys prevent cross-tenant policy, operation, OrgUnit,
  Project, instance, and stage references.
- Policy, payload, write-intent, binding, authorization-revision, and decision
  hashes use canonical `sha256:` references.
- The S70 repository exposes no decision mutation method; S73 will be the only
  writer and must append the decision and transition instance/stage state in
  one transaction.
- Database failures are returned as redacted typed errors.
- No credential, raw secret, or protected business payload is stored in these
  tables.

## Verification

- Focused S69/S70 regression: `77 passed`, `2 protected skips`.
- Actual PostgreSQL test migration: `2510` applied to `nex_eos_test`.
- Actual PostgreSQL protected smoke: `1 passed`, no skip.
- Protected smoke verified database/role identity, instance and two-stage
  creation, restart-style exact replay/readback, one active stage, empty
  decision history, tenant isolation, and zero residue.
- NeX-EOS Slice Gate: `456 passed`, `15 protected skips`.
- EOS Slice Gate statement coverage: `99.56%`.
- EOS Slice Gate branch coverage: `99.61%`.
- New approval-instance module statement coverage: `97.23%`.
- New approval-instance module branch coverage: `95.24%`.
- Contract validation: `188` schemas, `250` examples, `217` negative examples,
  and `9` OpenAPI documents.
- Ruff and Black checks: passed.

Remote embedding, reranking, and generation providers were not required.
Formal business approval state is deterministic EOS data, not model output.

## Exit Decision

P8-S70 is closed. P8-S71 can project the single active EOS stage to WC as a
`BUSINESS_FORMAL` approval work item while preserving the instance, policy,
payload, write-intent, and stage lineage established here.
