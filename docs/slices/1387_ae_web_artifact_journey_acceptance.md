# Slice 1387: AE Web Artifact Journey Acceptance

## Outcome

- Reused the production AE Web artifact client to extend the same correlated
  golden journey through asynchronous render completion, owner-scoped preview,
  and owner-scoped download acceptance.
- Required a completed render job, READY artifact, all requested formats, and
  exact artifact-file lineage before advancing each browser stage.
- Selected `HTML_PREVIEW` for preview and `MD` for download when available,
  while retaining deterministic fallbacks for supported artifact formats.
- Returned only opaque identifiers, format/content metadata, lengths, and hash
  presence. Preview text, download bytes, file names, and storage references
  remain transient and absent from browser evidence.

## Decisions

- Artifact, preview, and download failures terminate at distinct stages and do
  not expose backend error messages or private payloads.
- Preview and download must resolve to files from the exact rendered artifact;
  route availability alone is insufficient.
- This Slice adds no table and requires neither PostgreSQL nor a remote model
  provider. Protected browser and test-database evidence remains in Slice 1390.

## Verification

- Node regression covers the complete nine-stage journey, incomplete render,
  incomplete formats, preview/download failure mapping, retryability, content
  redaction, and artifact-file lineage mismatch.
- Repository smoke freezes the three artifact operations, exact completion
  guards, three terminal failure phases, and metadata-only return projection.

## Next

Slice 1388 hardens responsive layout, accessibility, and non-overlap checks for
the desktop and mobile acceptance viewports.
