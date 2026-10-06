# Slice 1385: AE Web Login, Upload, and Ingestion Acceptance

## Outcome

- Added an AE same-origin upload-progress client for
  `/api/v1/uploads/{upload_handoff_id}/progress` with owner-scoped,
  metadata-only normalization.
- Added a correlated login, upload, and ingestion workflow that advances the
  first three golden-journey stages under one `journey_id`.
- Derived upload ownership only from the authenticated OA browser session and
  rejected browser-supplied owner scope or response/session mismatches.
- Added bounded progress polling and required `INDEX_READY` plus
  `retrieval_usable=true` before the ingestion stage can complete.
- Wired the progress client into the shared client registry and upload surface.

## Decisions

- Browser credentials are sent only to the existing session client and never
  enter journey state, summaries, or evidence.
- AE Web calls only the same-origin AE facade; it does not call CX directly.
- Progress failure evidence contains a bounded phase code and retryability,
  never raw service or provider errors.
- No database migration or remote model provider is required.

## Verification

- Node unit regression covers mock/fetch progress, same-origin credentials,
  malformed and unsafe projections, claim-derived ownership, bounded polling,
  terminal failure, owner mismatch, and private-error redaction.
- Repository smoke freezes the AE progress route, three ordered stages,
  client-registry/main wiring, OA claim authority, and no direct CX call.

## Next

Slice 1386 adds retrieval, grounded generation, warning, citation, and repair
acceptance to the same journey and runs the fifth-Slice Checkpoint Gate.
