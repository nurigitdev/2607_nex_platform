# Slice 0194: CX Source Ownership Schema Migration

## Scope

Slice 0194 adds PostgreSQL schema support for canonical OA-owned source
ownership references in CX, without changing the existing runtime repository
write path yet.

Implemented:

- `0194_cx_source_ownership_schema_migration.sql`
- decomposed, indexable ownership columns on `cx_content_objects`
- decomposed ACL subject columns on `cx_content_acl_entries`
- PostgreSQL backfill from legacy `tenant_id` / `owner_user_id`
- compatibility triggers so legacy inserts continue to populate canonical refs
- schema foundation regression checks
- current next-slice pointers moved to `0195_cx_owner_scoped_repository_api_wiring`

## Content Object Columns

`cx_content_objects` now has:

- `tenant_ref_type`
- `tenant_ref_id`
- `owner_subject_ref_type`
- `owner_subject_ref_id`
- `uploaded_by_subject_ref_type`
- `uploaded_by_subject_ref_id`

The migration backfills these from existing legacy fields:

```text
tenant_ref_type = oa.tenant
tenant_ref_id = tenant_id
owner_subject_ref_type = oa.user
owner_subject_ref_id = owner_user_id
uploaded_by_subject_ref_type = oa.user
uploaded_by_subject_ref_id = owner_user_id
```

## Index Strategy

The canonical owner-scoped duplicate key is now indexable as plain columns:

```text
tenant_ref_type
tenant_ref_id
owner_subject_ref_type
owner_subject_ref_id
source_sha256
```

The existing legacy unique index remains in place so current behavior does not
change before repository/API wiring moves in Slice 0195.

## ACL Columns

`cx_content_acl_entries` now has:

- `principal_ref_type`
- `principal_ref_id`
- `granted_by_subject_ref_type`
- `granted_by_subject_ref_id`

Current owner grants map `principal_type = user` to `principal_ref_type =
oa.user`. The migration also allows existing group/service ACL rows to map to
`oa.group` and `service` without requiring OA group support yet.

## Compatibility Trigger

The migration installs PostgreSQL triggers that populate canonical ref columns
from legacy fields when older code paths omit them. This keeps current upload
and repository behavior stable until Slice 0195 explicitly writes and reads
the new columns.

## Boundary

The migration intentionally does not add foreign keys from CX to OA tables.
Current deployment keeps service databases separate, and even a future
single-PostgreSQL deployment may preserve logical service ownership through
schemas. CX stores stable OA refs, not OA-owned identity records.

## Next Slice

Recommended next slice:

- `0195_cx_owner_scoped_repository_api_wiring`

That slice should update CX repository/API behavior to write and read canonical
subject refs directly while retaining legacy request compatibility.

## Evidence

Targeted regression:

```bash
./.venv/bin/pytest tests/test_database_schema_foundation.py tests/test_nex_cx_source_ownership.py tests/test_nex_cx_persistence_audit.py tests/test_nex_cx_processing_persistence.py tests/test_nex_oa_subjects.py tests/test_contract_validation.py -q
```

Full quality gate:

```bash
./scripts/quality/run_quality_gate.sh
```
