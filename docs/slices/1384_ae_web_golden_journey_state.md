# Slice 1384: AE Web Correlated Golden-Journey State

## Outcome

- Added one immutable browser journey model from authenticated session through
  download readiness under a single opaque `journey_id`.
- Enforced nine ordered stages, monotonic timestamps, terminal-state guards,
  opaque-reference allowlists, and bounded detail allowlists.
- Added a browser-safe evidence projection that excludes credentials, prompts,
  document/generated text, source bytes, storage refs, provider URLs, database
  URLs, and local data paths.
- Initialized the model in AE Web composition without changing current service
  calls or persisting new browser state.

## Decisions

- The journey model correlates UI acceptance evidence; it is not a new source
  of truth for OA, AE, CX, MO, or AG domain state.
- A stage cannot be skipped, repeated, or appended after completion/failure.
- Quality repair is represented by bounded `quality_status` and
  `repair_attempt_count`; repaired content never enters journey evidence.
- No new database table or remote provider is required.

## Verification

- Node unit regression covers full completion, order violations, terminal
  mutation, malformed state, unsafe fields, timestamp rollback, and redaction.
- Repository smoke freezes the nine-stage order, allowlists, main composition
  wiring, and evidence privacy contract.

## Next

Slice 1385 drives login, upload, and ingestion progress through this correlated
state without bypassing the same-origin AE facade.
