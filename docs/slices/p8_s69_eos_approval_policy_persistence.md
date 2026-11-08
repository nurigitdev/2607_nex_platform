# P8-S69: EOS ApprovalPolicy Persistence

## Status

Completed on 2026-10-23.

## Scope

NeX-EOS is now the persistence owner for deterministic formal approval policy
definitions. This Slice adds:

- `eos_approval_policy` for tenant-scoped, versioned policy identity, selectors,
  effective period, status, and semantic hash;
- `eos_approval_policy_stage` for one to five ordered leadership stages;
- a SQLAlchemy repository for immutable create, exact readback, and effective
  policy resolution;
- optional Project and Account selector references constrained to the same EOS
  tenant;
- EOS dependency-container and application-state wiring;
- migration `2509_eos_approval_policy`.

ApprovalInstance, active-stage state, decisions, WC work projection, and final
ApprovalProof remain outside P8-S69. They start in P8-S70 and later Slices.

## Deterministic Selection

A selection request carries the approval domain, risk, non-negative Decimal
amount, Project, Account set, transaction type, and effective timestamp.
Selectors left null in a policy are wildcards. Amount intervals are half-open:

```text
minimum_amount <= amount < maximum_amount
```

The resolver chooses the matching policy with the greatest number of explicit
selector fields. If two or more matching policies have equal specificity, it
does not use insertion order, lexical order, or an LLM to break the tie. It
fails closed with `EOS_APPROVAL_POLICY_AMBIGUOUS`.

No matching `BUSINESS_FORMAL` policy means no formal business-approval policy
is enabled for that operation. It does not imply approval and does not reuse
`NSL_WRITE` or `AGENT_FORMAL` evidence.

## Stage Profile

The persisted stage model supports an ordered subset of:

```text
PART_LEAD -> TEAM_LEAD -> GROUP_LEAD -> CEO -> CHAIRMAN
```

Repeated or reverse-order positions are rejected. `quorum_count` and
`separation_policy` are explicit persistence fields so later policy versions
can evolve without replacing the stage model. The initial P8.7 profile admits
only:

```text
quorum_count = 1
separation_policy = REQUESTER_EXCLUDED
```

No-self-approval enforcement remains preserved for the subsequent approver
resolution and stage-execution Slices.

## Persistence Safety

- Policy identity is unique by `(tenant_id, approval_policy_id)`.
- Policy version is unique by `(tenant_id, policy_key, version)`.
- The canonical policy definition, including ordered stages, is protected by a
  `sha256:` semantic hash.
- Project and Account references are composite tenant-scoped foreign keys.
- Active-period evaluation is timezone-aware and uses a half-open end.
- Database failures expose redacted typed errors.
- No credential, raw secret, human decision, or protected business payload is
  stored in either policy table.

The historical P8-S22 migration test now locates its owned `2508` migration by
version instead of assuming it remains the permanent EOS migration head.

## Verification

- Focused policy regression: `44 passed`, `1 protected skip`.
- New policy module statement coverage: `100%`.
- New policy module branch coverage: `100%`.
- Actual PostgreSQL test migration: `2509` applied to `nex_eos_test`.
- Actual PostgreSQL protected smoke: `1 passed`, no skip.
- Protected smoke verified database/role identity, referenced Project and
  Account persistence, policy create, restart-style repository readback,
  deterministic selection, tenant isolation, and zero residue.
- NeX-EOS Slice Gate: `423 passed`, `14 protected skips`.
- EOS Slice Gate statement coverage: `99.82%`.
- EOS Slice Gate branch coverage: `100.00%`.
- Contract validation: `188` schemas, `250` examples, `217` negative examples,
  and `9` OpenAPI documents.
- Ruff and Black checks: passed.

Remote embedding, reranking, and generation providers were not required. Formal
approval routing is deterministic business policy, not model output.

## Exit Decision

P8-S69 is closed. P8-S70 can create immutable ApprovalInstance and
ApprovalStage runtime state from the exact selected policy ID, version, hash,
and ordered stage snapshot without changing this policy SoR.
