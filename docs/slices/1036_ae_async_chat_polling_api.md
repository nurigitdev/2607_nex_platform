# Slice 1036: AE Asynchronous Chat Polling API

## Goal

Expose an owner-scoped explicit refresh operation that converges durable AE
interaction state from the canonical CX generation handoff.

## Implementation

- Added `POST /api/v1/chat/interactions/{interaction_id}/refresh`.
- Refresh reads the CX owner-scoped handoff and maps `PENDING`, `READY`, and
  `BLOCKED` into AE `PENDING`, `COMPLETED`, and `FAILED` interaction states.
- READY content is integrity-checked by SHA-256 and byte size, returned only in
  the refresh response, and never stored in AE interaction JSON.
- Persisted projections update attempts, safe links, job status, handoff status,
  and safe failure codes without raw provider or content data.
- Missing, synchronous, malformed, owner-unsafe, and tampered handoffs fail
  closed before state mutation.

## Verification

```bash
scripts/quality/run_checkpoint_gate.sh --service nex-ae-api \
  --test tests/test_ae_async_chat_refresh.py \
  --coverage-target services/nex-ae-api/nex_ae_api/async_generation.py
```

The Checkpoint Gate covers S104 Slices 1032-1036. No provider call is required.

## Observed Evidence

- Focused async contract/refresh tests: `77 passed` with one known warning.
- S104 focused tests after drift-audit hardening: `87 passed`.
- Checkpoint Gate: `7797 passed` with 123 known warnings.
- Checkpoint statement coverage: `98.66%`.
- Checkpoint branch coverage: `96.60%`.
- Async contract statement/branch coverage: `100%`/`100%`.
- Contract validation: 96 schemas, 150 positive examples, 113 negative
  examples, and 7 OpenAPI documents.
- The first Checkpoint run detected a stale exact-count route inventory. The
  audit now enforces non-regressing inventory baselines and complete drift
  classification, then the Checkpoint passed.
