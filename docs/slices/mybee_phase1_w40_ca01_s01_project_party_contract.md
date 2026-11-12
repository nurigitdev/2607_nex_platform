# W40-CA01-S01 Project Party and Initial Membership Application Contract

## Status

`CLOSED` on 2026-11-12.

This Slice implements the first W40-CA01 boundary before W40 accounting
posting. Project applicant, accountable owner, operating PM, and initial
members are now explicit application concepts rather than an implicit
applicant-as-owner shortcut.

## Implemented Boundary

- Added required `project_owner_subject_id` and
  `project_manager_subject_id` application fields.
- Added typed `ProjectApplicationMember` entries and bounded initial-member
  admission for `OWNER`, `MANAGER`, `MEMBER`, and `VIEWER`.
- Normalized owner and PM into the immutable v2 application revision:
  - owner becomes one `OWNER`;
  - a distinct PM becomes one `MANAGER`;
  - the same owner/PM subject remains one `OWNER` while the PM binding is
    preserved;
  - duplicate subjects and conflicting owner/PM roles fail closed.
- Kept the applicant outside Project access unless explicitly admitted as an
  owner, PM, or initial member.
- Reused the immutable `eos_project_app_revision.payload_json` for the complete
  normalized member set instead of introducing a duplicate application-member
  table.
- Added fresh OA tenant/subject activity checks for every normalized party
  before submission.
- Preserved PATCH semantics by merging omitted fields from the current immutable
  revision before creating the next revision.

## Persistence

Migration `2536_eos_project_application_parties.sql` adds the current owner and
PM identity to `eos_project_application`, supporting indexes, and a DRAFT-only
party-change guard tied to revision advancement.

Historical pre-v2 applications are backfilled to applicant-as-owner/PM only as
a migration compatibility fact. New v2 requests cannot omit either identity.
The migration records its exact version in `schema_migrations`.

## Validation Evidence

Focused Project application and committee regression:

```text
69 passed, 2 protected skips
```

NeX-EOS Slice Gate:

```text
status: PASS
commands: 5/5
tests: 1456 passed, 45 protected skips
statement coverage: 96.31% (threshold 96.00%)
branch coverage: 94.06% (threshold 94.00%)
contract validation: PASS (239 schemas, 297 examples, 248 negative, 10 OpenAPI)
Golden Journey transition audit: PASS
demo-to-product dependency audit: PASS
```

Machine-readable coverage evidence:

- `reports/quality/mybee-w40-ca01-s01.coverage.json`

The first Slice Gate run correctly failed because the new migration omitted its
`schema_migrations` receipt. The receipt was added and the complete gate was
rerun successfully; the failed run is not presented as acceptance evidence.

## Preserved Boundaries

- EOS remains the Project application and membership business SoR.
- OA party checks do not yet persist Project entitlement; that is S03.
- Final approval still uses the historical applicant membership behavior until
  S02 replaces it with the admitted owner/PM/member materialization.
- Project UUID technical identity and Project-Code business identity are
  unchanged.
- No remote model provider is required.

## Next Entry

`W40-CA01-S02` materializes the exact submitted owner, PM, and initial-member
revision during final committee approval and removes implicit applicant
membership from the new product path.
