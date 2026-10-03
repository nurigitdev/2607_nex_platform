# Slice 1232: OA group and role authorization boundary

## Goal

Start S124 by freezing tenant isolation, grant composition, mutation,
session-invalidation, persistence, evidence, and deferred trust boundaries.

## Decision

- NeX-OA owns tenant-scoped role definitions, groups, group membership, role
  assignment, and effective authorization projection.
- Effective grants are the set union of compatible direct membership grants
  and active group-role grants. Unknown roles and inactive principals fail
  closed. Explicit deny and nested groups are not part of the initial model.
- Group, role, membership, and assignment changes require optimistic revision
  checks and append privacy-safe authorization events.
- Authorization changes revoke active sessions for affected users. Session
  claims remain an issue-time snapshot and cannot retain stale grants.
- Management mutations require `authorization:admin`, reads require
  `authorization:read`, and compatibility ensure routes require the distinct
  `identity:bootstrap:write` scope.
- Short table names are fixed as `oa_roles`, `oa_groups`, `oa_group_members`,
  `oa_group_roles`, and `oa_authz_events`.
- Actual `nex_oa_test` evidence is mandatory. DGX and remote model providers
  are outside this requirement.
- Signed service tokens and JWKS verification remain a separate trust
  requirement.

## Slice Plan

Slices 1232 through 1241 cover boundary, domain policy, migration, durable
repository, effective grants and session integration, protected admin APIs,
bootstrap authorization, contracts/privacy, PostgreSQL evidence, and closure.
Slice Gate runs per Slice, Checkpoint Gate at 1236, and Full Gate at 1241.

## Verification

```bash
./scripts/quality/run_slice_gate.sh \
  --service nex-oa \
  --test tests/test_oa_group_role_authorization_boundary.py \
  --coverage-target scripts/smoke/run_oa_group_role_authorization_boundary.py \
  --smoke scripts/smoke/run_oa_group_role_authorization_boundary.py
```
