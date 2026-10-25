# P8-S94: EOS Project Membership Persistence Foundation

## Status

Completed on 2026-10-25.

## Scope

P8-S94 added the EOS-owned persistence foundation required by P8-CA04. It did
not add public membership lifecycle APIs, OA authorization, NSL contracts, or
Voucher admission changes; those remain assigned to P8-S95 and later slices.

The additive `2514_eos_project_member` migration creates one authoritative
`eos_project_member` table with:

```text
tenant-scoped membership and Project identities
one durable relationship per tenant / Project / subject
OWNER, MANAGER, MEMBER, and VIEWER roles
ACTIVE and REMOVED lifecycle states
validity, actor, version, and timestamp lineage
same-tenant composite foreign key to eos_project
Project and subject lookup indexes
no direct OA foreign key and no physical-delete path
```

The table, constraint, and index identifiers remain below PostgreSQL's
identifier limit. Existing P8-S93 migrations remain immutable.

## Runtime Foundation

`SqlAlchemyEosProjectMembershipRepository` provides strict create and
tenant-scoped get operations for the next lifecycle slice. It validates IDs,
roles, states, validity windows, and terminal removal shape; rejects a missing
same-tenant Project; maps uniqueness violations to a typed conflict; and
redacts persistence failures.

EOS dependency and application state wiring now expose the repository without
changing any public API route.

## Verification

Focused SQLite regression and branch coverage:

```text
19 passed
statement coverage = 100%
branch coverage    = 100%
```

Actual PostgreSQL execution:

```text
database = nex_eos_test
user     = nex_eos_user
migration applied = 2514_eos_project_member
protected smoke   = 1 passed / 0 skipped
```

The protected smoke verifies database identity, migration presence,
same-tenant Project creation, membership insert/read, and cleanup residue.

EOS regression:

```text
630 passed
19 expected protected skips
0 failed
```

## Exit Decision

P8-S94 is closed. EOS has one authoritative, tenant-isolated Project
membership persistence foundation. P8-S95 may add idempotent ADD/REMOVE,
reactivation, concurrency protection, and the last-active-OWNER invariant
without introducing another membership table.
