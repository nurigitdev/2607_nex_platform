# Slice 1037: AE Asynchronous Chat Cancel and Retry

## Goal

Add owner-scoped cancellation and explicit retry without duplicating private
generation material or losing lineage.

## Implementation

- Added owner-scoped cancel and retry routes below each chat interaction.
- Cancellation delegates to CX, converges the returned job projection, and is
  idempotent after `CANCELLED`.
- Completed and already-blocked non-cancelled jobs reject cancellation.
- Retry is allowed only for a retryable `BLOCKED` projection, requires a new
  interaction ID, and verifies the submitted user-message hash against the
  original interaction.
- Retry creates a new CX admission and stores only parent interaction, job, and
  generation IDs as lineage; raw input is excluded.
- Cross-owner operations remain indistinguishable from not found.

## Verification

```bash
scripts/quality/run_slice_gate.sh --service nex-ae-api \
  --test tests/test_ae_async_chat_cancel_retry.py \
  --coverage-target services/nex-ae-api/nex_ae_api/chat.py
```

Tests use in-memory stores and a deterministic lifecycle client. No database or
provider call is required.

## Observed Evidence

- Focused cancel/retry and async contract tests: `84 passed` with one known
  warning.
- Slice Gate: `2203 passed` with one known warning.
- Repository statement coverage: `97.91%`.
- Repository branch coverage: `95.75%`.
- Chat module statement/branch coverage: `97.62%`/`97.62%`.
- Async contract statement/branch coverage remains `100%`/`100%`.
- Contract validation: 96 schemas, 150 positive examples, 113 negative
  examples, and 7 OpenAPI documents.
- Earlier Gate runs identified a remaining exact-count drift assertion and
  under-covered cancel/retry error branches; both were hardened before the
  successful Gate.
