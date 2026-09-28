# Slice 1035: AE Asynchronous Chat Admission

## Goal

Wire explicit asynchronous chat requests into durable CX admission while
preserving the existing synchronous AE chat behavior.

## Implementation

- Added an injectable/default CX asynchronous client to AE chat composition.
- Resolved `generation.execution_strategy` after owner/workspace binding and
  before runtime execution.
- Reused the existing durable AE `PENDING` interaction, then stored the
  allowlisted CX job projection and exact S103 policy package in
  `generation_summary`.
- Returned `202` for a newly admitted asynchronous interaction while keeping
  synchronous requests and idempotent replays backward compatible.
- Derived the CX admission idempotency key from the stable AE interaction ID.
- Routed transport/contract failures through the existing durable failed-chat
  path without persisting raw error detail.

## Verification

```bash
scripts/quality/run_slice_gate.sh --service nex-ae-api \
  --test tests/test_ae_async_chat_admission.py \
  --coverage-target services/nex-ae-api/nex_ae_api/chat.py
```

SQLite restart regression proves durable projection round trips. No provider or
PostgreSQL call is required in this Slice.

## Observed Evidence

- Focused async plus existing chat compatibility tests: `62 passed`.
- Slice Gate: `2160 passed` with one known warning.
- Repository statement coverage: `97.90%`.
- Repository branch coverage: `95.72%`.
- Chat module statement/branch coverage: `97.69%`/`98.26%`.
- Contract validation: 96 schemas, 150 positive examples, 113 negative
  examples, and 7 OpenAPI documents.
