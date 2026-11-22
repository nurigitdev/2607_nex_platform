# W40-CA01-S02 Approval Membership Materialization

## Status

`CLOSED` on 2026-11-12.

This Slice removes the historical applicant-as-owner shortcut from the new
Project approval path. Final committee approval now materializes the exact
owner, PM, and initial-member revision admitted by S01.

## Implemented Boundary

- Added canonical owner and PM responsibility fields to approved Projects.
- Revalidated every submitted Project party against fresh OA subject activity
  immediately before the final approval mutation.
- Created one deterministic membership per normalized submitted party:
  - owner as `OWNER`;
  - distinct PM as `MANAGER`;
  - each explicit initial member with its admitted role;
  - applicant only when explicitly present in that normalized set.
- Kept Project creation, membership materialization, lifecycle outbox append,
  approval finalization, and application finalization in one EOS transaction.
- Preserved deterministic replay and pre-v2 applicant-as-owner/PM compatibility.
- Rejected malformed, duplicated, role-drifted, non-canonical, inactive,
  cross-tenant, or unavailable party projections fail closed.

## Persistence

Migration `2537_eos_project_approved_parties.sql` adds indexed
`project_owner_subject_id` and `project_manager_subject_id` columns to
`eos_project` and records its exact `schema_migrations` receipt.

Historical approved Projects are backfilled from their application when that
lineage exists. The approved-party constraint is installed `NOT VALID`, so it
protects all new writes without inventing identities for unrelated historical
rows. The product repository independently requires both fields for every new
`APPROVED_APPLICATION` Project.

## Validation Evidence

Focused Project application, committee, and Project Agent regression:

```text
100 passed, 3 protected skips
```

Protected `nex_eos_test` PostgreSQL migration/finalization smoke:

```text
1 passed
Project rows: 1
committee decision rows: 1
exact membership rows: 3
temporary schema residue: 0
```

NeX-EOS Slice Gate:

```text
status: PASS
commands: 5/5
tests: 1471 passed, 45 protected skips
statement coverage: 96.33%
branch coverage: 94.11%
contract validation: PASS
Golden Journey transition audit: PASS
demo-to-product dependency audit: PASS
```

Machine-readable coverage evidence:

- `reports/quality/mybee-w40-ca01-s02.coverage.json`

The first complete regression exposed one legacy voucher fixture that omitted
the newly required approved-Project parties; the fixture was corrected without
weakening the product contract. A subsequent gate found branch coverage at
`93.80%`; corruption and authorization rejection branches were then covered,
and the complete gate was rerun successfully.

## Preserved Boundaries

- EOS remains the business SoR for Project and membership state.
- OA Project-code entitlement persistence and decisions are not introduced
  here; that is W40-CA01-S03.
- No EOS membership list is embedded in tokens or copied into OA yet.
- Existing UUID technical identity and Project-Code business identity remain
  unchanged.
- No remote model provider is required.

## Next Entry

`W40-CA01-S03` adds the OA Project-code entitlement projection and exact
tenant/subject/project/action decision contract, followed by the schema/API
Checkpoint Gate.
