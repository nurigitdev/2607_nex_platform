# Slice 1043: AE Generation Progress Contract

## Goal

Define a deterministic, privacy-safe AE projection for asynchronous generation
progress and recovery readiness before adding orchestration or HTTP routes.

## Implementation

- Added `ae_generation_progress.v1` with owner-bound job and generation IDs,
  lifecycle status, canonical event type, user-facing stage key, polling advice,
  cancellation capability, terminal state, and bounded attempt metadata.
- Added `ae_generation_recovery_plan.v1` with deterministic `WAIT`, `NONE`,
  `RETRY_AS_CHILD`, and `REVIEW_REQUIRED` decisions.
- Mapped queued, running, finalizing, completed, failed, and cancelled states
  without claiming token-level streaming progress.
- Completed progress is determinate at 100%; all non-completed progress remains
  indeterminate to avoid fabricated percentages.
- Added strict shape, state consistency, attempt-bound, detached-copy, nested
  privacy, and tampered-recovery validation tests.

## Decisions

- The contract is a current owner-scoped snapshot, not an append-only event
  history or server-sent event stream.
- Recovery eligibility is advisory and read-only. Execution remains an explicit
  child admission in a later Slice.
- Generated content, raw prompts, raw errors, evidence text, provider runtime,
  and credentials are prohibited.
- No database migration, PostgreSQL access, or remote provider is required.

## Verification

```bash
scripts/quality/run_slice_gate.sh --service nex-ae-api \
  --test tests/test_nex_ae_generation_progress.py \
  --coverage-target services/nex-ae-api/nex_ae_api/generation_progress.py
```

## Observed Evidence

- Slice Gate: PASS (`2255 passed`, `1` protected PostgreSQL smoke skipped).
- Repository statement coverage: `97.88%`.
- Repository branch coverage: `95.70%`.
- Progress contract focused tests: `33 passed` with statement/branch coverage
  `100.00%`/`100.00%`.
- Contract validation: 98 schemas, 153 positive examples, 116 negative
  examples, and 7 OpenAPI documents.
