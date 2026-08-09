# Slice 0163: CX SQLAlchemy Upload Duplicate Regression

## Scope

Slice 0163 proves the new SQLAlchemy CX content repository works through the
existing upload ingestion boundary.

Implemented:

- `ContentIngestionStore` regression with `SqlAlchemyCxContentRepository`
- same-owner duplicate upload proof for `tenant_id + owner_user_id + source_sha256`
- cross-owner upload proof that content objects stay separate while sharing one
  source file metadata row
- owner ACL row count checks for SQLAlchemy-backed content objects
- database dump assertions that raw upload payload text does not enter
  `cx_source_files`, `cx_content_objects`, or `cx_content_acl_entries`

## Behavior Fixed As Baseline

Same tenant, same owner, same source hash:

```text
cx_source_files=1
cx_content_objects=1
cx_content_acl_entries=1
second_upload.dedupe.status=ALREADY_EXISTS
```

Same tenant, different owner, same source hash:

```text
cx_source_files=1
cx_content_objects=2
cx_content_acl_entries=2
both_uploads.dedupe.status=CREATED
```

This preserves the product decision that source bytes are globally deduplicated
by hash, while readable content ownership is scoped per user.

## Evidence

Targeted regression:

```bash
./.venv/bin/pytest tests/test_nex_cx_repository.py
```

Expected result:

```text
23 passed
```
