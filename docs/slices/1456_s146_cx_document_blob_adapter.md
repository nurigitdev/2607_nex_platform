# Slice 1456: S146 CX Document Blob Adapter

## Outcome

- Added a CX document-blob port backed by the shared S3-compatible client.
- Moved uploaded source bytes to immutable content-addressed objects while
  retaining owner-scoped content authorization and global physical dedupe.
- Moved extracted Markdown to opaque owner-scoped objects and persisted only
  its storage reference, SHA-256, size-derived metadata, and lineage.
- Added verified source fallback and restart hydration from object storage.
  Hydrated Markdown is materialized only under the extraction temporary root
  for existing chunking and summary adapters.
- Kept the filesystem mode backward compatible and made invalid or incomplete
  S3 configuration fail closed.

## Quality

- Focused tests cover source and Markdown round trips, opaque keys, owner
  denial, invalid sharding, oversize and checksum rejection, missing objects,
  UTF-8 corruption, retryable storage failures, mode selection, persisted
  metadata, S3 source fallback, and restart hydration.
- Existing filesystem ingestion, repository, and hydration behavior remains
  covered by the same focused regression set.
- Focused regression passed 262 tests with 100% coverage for the new document
  adapter and 97% combined coverage with hydration. Slice Gate passed 2,496
  tests with 98.88% statement coverage and 97.83% branch coverage; the changed
  adapter remained at 100% statement and branch coverage.
- Contract validation passed with 166 schemas, 228 examples, 196 negative
  examples, and 7 OpenAPI documents.
