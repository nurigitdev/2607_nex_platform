# Slice 1039: AE Asynchronous Chat Contract and OpenAPI

## Goal

Freeze the implemented AE-to-CX asynchronous generation lifecycle as strict,
privacy-aware JSON Schema and OpenAPI contracts.

## Implementation

- Added canonical `ae_async_generation.v1` JSON Schema for owner-safe durable
  job projection state, attempts, links, errors, and lifecycle consistency.
- Added canonical `ae_async_chat_refresh.v1` JSON Schema for explicit refresh,
  transient verified content, and the invariant that AE does not persist that
  content.
- Extended `ae_chat_interaction.v1` with async CX statuses, strict async
  projection and retry-lineage shapes, and nullable non-failure state.
- Added queued interaction and READY refresh positive examples.
- Added negative fixtures for generated-content persistence, async projection
  content leakage, and provider endpoint leakage.
- Upgraded AE OpenAPI to `1.2.0` with explicit create `202`, refresh, cancel,
  retry, async projection, retry lineage, and refresh response contracts.

## Verification

```bash
scripts/quality/run_slice_gate.sh --service nex-ae-api \
  --test tests/test_ae_async_chat_contracts.py \
  --coverage-target services/nex-ae-api/nex_ae_api/async_generation.py
```

No database or remote provider is required for this contract Slice.

## Observed Evidence

- Focused contract validation and API regression: `116 passed`.
- Contract validation before the Slice Gate: 98 schemas, 153 positive
  examples, 116 negative examples, and 7 OpenAPI documents.
- Slice Gate: `2214 passed` with one known warning.
- Repository statement coverage: `97.89%`.
- Repository branch coverage: `95.71%`.
- Async generation contract runtime statement/branch coverage: `100%`/`100%`.
- Final contract validation: 98 schemas, 153 positive examples, 116 negative
  examples, and 7 OpenAPI documents.
