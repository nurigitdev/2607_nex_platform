# P8-S10: EOS Organization Core

Completed on 2026-10-21. NeX-EOS now owns the minimum durable business
organization model required by later approval-routing slices.

## Scope

- Added migration `2502_eos_organization_core`.
- Added `eos_org_unit`, `eos_position`, and `eos_position_assignment`.
- Added tenant-scoped SQLAlchemy organization persistence and effective
  assignment lookup.
- Wired the repository into the EOS runtime whenever its database runtime is
  configured.
- Kept approver resolution, reporting policy, ActingAuthority, public routes,
  and OA authorization outside this Slice.

## Ownership Boundary

EOS owns organization units, business positions, and their effective-dated
assignments. OA remains the identity and authorization SoR. An assignment
stores only an exact stable OA user reference as split, indexable fields:

```text
principal_ref_type = oa.user
principal_id       = stable OA subject id
```

No credential, authentication state, token, or copied OA user profile is
stored in EOS.

## Integrity

All references are tenant-qualified composite foreign keys. Organization types
are limited to `PART`, `TEAM`, `GROUP`, and `COMPANY`; positions are limited to
the canonical `PART_LEAD -> TEAM_LEAD -> GROUP_LEAD -> CEO -> CHAIRMAN` policy
vocabulary. Status, effective periods, UUID identities, positive versions, and
stable-reference syntax fail closed.

Only one `ACTIVE` assignment may exist for a position. The repository checks
this before insertion and PostgreSQL enforces it with a partial unique index,
covering concurrent writers as well. An assignment is effective only when its
status is active and the requested instant is inside its half-open effective
period.

## Verification

- EOS S07-S10 regression: `89 passed`, with protected PostgreSQL tests skipped
  only in the ordinary Slice Gate.
- EOS Slice Gate: statement coverage `100%`, branch coverage `100%`.
- Contract validation: 174 schemas, 236 examples, 204 negative examples, and
  9 OpenAPI documents.
- Actual dev/test PostgreSQL migration applied `2502` after `2500/2501`.
- Protected S10 smoke connected as `nex_eos_user@nex_eos_test` and verified
  effective lookup, duplicate-active denial, tenant isolation, and final zero
  residue.
- The existing protected S08 migration/reset smoke passed with all S10 tables
  present.
- All table, constraint, and index names remain below PostgreSQL's 63-byte
  identifier limit.
- Remote model providers were not required.

The Platform Full Gate was not repeated. P8-S10 follows the Slice Gate cadence;
P8-S11 runs the requested Checkpoint Gate.
