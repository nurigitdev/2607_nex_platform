# Slice 1459: S146 Object Storage Lifecycle And Restore

## Outcome

- Added idempotent private bucket bootstrap with versioning, default SSE-S3,
  bounded multipart cleanup, hold-aware noncurrent retention, delete-marker
  cleanup, and read-back policy verification.
- Added explicit purge admission from active reference count, legal hold,
  durable purge decision, and rollback-window state.
- Added version tagging that preserves existing tags and makes only admitted
  versions eligible for the 30-day noncurrent lifecycle rule. No destructive
  version-delete API was introduced.
- Added historical version restore with owner-prefix validation, bounded read,
  SHA-256/size/content-type/SSE verification, immutable current-version
  publication, and post-publication read verification.
- Added a protected CX/AE bucket lifecycle runner using dedicated
  `NEX_OBJECT_STORAGE_BOOTSTRAP_*` credentials with redacted evidence.

## Safety Decisions

- Untagged versions never enter automatic noncurrent expiration, so bucket
  lifecycle cannot override a service legal hold or active reference.
- Expired delete-marker cleanup cannot remove a marker while a held or other
  retained object version still exists.
- Restore never removes a delete marker or mutates an old version. It creates a
  new verified current version and refuses an already-active target.
- Bootstrap secrets, endpoint, bucket name, object key, version IDs, and
  payload bytes do not appear in source-controlled evidence.
- RustFS compatibility for versioning, lifecycle rules, version tagging, and
  version-specific reads remains a protected live acceptance item for Slice
  1461.

## Quality

- Focused tests cover policy shape and drift, create/existing bucket paths,
  S3 failures, purge guards and malformed tags, restore integrity and outage
  paths, bootstrap configuration, and CLI redaction.
- Focused regression: `29 passed`; combined statement and branch coverage
  `99%`.
- Platform Slice Gate: `363 passed`, `6 skipped`; statement coverage `99.02%`,
  branch coverage `98.78%`; lifecycle module scope `99.16%/98.57%`, operator
  runner scope `98.53%/100%`.
- Contract validation passed with `166` schemas, `228` examples, `196` negative
  examples, and `7` OpenAPI documents.
