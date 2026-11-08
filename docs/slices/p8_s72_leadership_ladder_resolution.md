# P8-S72: Leadership Ladder Resolution

## Status

Completed on 2026-10-23.

## Scope

NeX-EOS now resolves the active stage of a pending `BUSINESS_FORMAL`
ApprovalInstance against the canonical leadership ladder:

```text
PART_LEAD -> TEAM_LEAD -> GROUP_LEAD -> CEO -> CHAIRMAN
```

The persisted ApprovalPolicy may select any unique, forward-ordered subset. A
policy may therefore contain one, two, three or more stages without requiring
all five.

This Slice extends the existing `EosApproverResolutionService`; it does not add
a parallel resolver or a new database table. The S39 organization repository
remains the source for tenant-scoped, effective PositionAssignment lookup.

## Resolution Binding

`resolve_active_stage()` admits only an exactly matching combination of:

```text
pending BUSINESS_FORMAL ApprovalInstance
+ active ApprovalStage and active_stage_order
+ ordered policy-stage subset
+ REQUESTER_EXCLUDED / quorum=1 initial profile
+ exact tenant, OrgUnit, Project and policy binding
+ effective Position and PositionAssignment
```

The immutable resolution hash binds the instance and stage IDs, selected
leadership route, policy and instance binding hash, requester, OrgUnit,
Project, resolved OA user, Position, PositionAssignment version and OrgUnit
version. `resolved_at` is evidence metadata and is intentionally excluded from
the hash, so restart replay is deterministic.

Missing, inactive, cross-tenant, mismatched or malformed assignments fail
closed. Requester self-approval is denied. No automatic fallback to another
leadership level is performed.

## WC Integration And Ownership

The P8-S71 adapter now resolves the active stage before creating its WC work
item. The work item preserves all four decision targets:

```text
target_approver_ref = resolved OA user
target_role_ref = active leadership position type
target_org_scope_ref = ApprovalInstance OrgUnit
target_project_scope_ref = ApprovalInstance Project
```

The WC semantic hash additionally binds the EOS resolution hash/ref and the
resolved position/assignment versions. A changed assignment cannot silently
retarget an already-created stage: replay reaches the deterministic WC source
identity and fails closed on semantic drift.

EOS resolution identifies the intended business approver. It is not a security
authorization decision and returns `security_authorization = false`. WC owns
the durable human task, while S73 and OA remain responsible for fresh
decision-time authority validation and EOS stage transition.

## Persistence

No migration was required. Existing tables remain authoritative:

- `eos_approval_policy` and `eos_approval_policy_stage` for the selected route;
- `eos_approval_instance` and `eos_approval_stage` for runtime stage state;
- `eos_org_unit`, `eos_position` and `eos_position_assignment` for resolution;
- `wc_approval_work_item` for the durable human task.

## Verification

- Focused S39/S69/S70/S71/S72 regression: `159 passed`.
- Final focused S39/S71/S72 regression after fail-closed normalization:
  `85 passed`.
- One-, two-, three-plus and complete five-stage policy routes: passed.
- Resolver and WC adapter statement/branch coverage: `100% / 100%`.
- Actual `nex_eos_test` and `nex_wc_test` migrations: current,
  `applied=none`.
- Actual dual-PostgreSQL protected smoke: `1 passed`, no skip.
- PostgreSQL smoke verified database identities, effective assignment lookup,
  concrete WC target persistence, restart-style replay, tenant isolation and
  zero residue in both databases.
- NeX-EOS Slice Gate: `516 passed`, `16 protected skips`.
- EOS Slice Gate statement coverage: `99.60%`.
- EOS Slice Gate branch coverage: `99.65%`.
- Contract validation: `188` schemas, `250` examples, `217` negative examples
  and `9` OpenAPI documents.
- Ruff, Black and `git diff --check`: passed.

Remote embedding, reranking and generation providers were not required.

## Exit Decision

P8-S72 is closed. P8-S73 can consume an OA-authorized WC decision, validate it
against the resolved active stage, and atomically advance to the next stage or
produce the final immutable ApprovalProof.
