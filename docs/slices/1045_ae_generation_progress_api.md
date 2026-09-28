# Slice 1045: AE Generation Progress API

## Goal

Expose owner-scoped polling of privacy-safe asynchronous generation progress
through the AE facade.

## Implementation

- Added `GET /api/v1/chat/interactions/{interaction_id}/progress`.
- Reused AE route authentication and owner-scoped interaction visibility.
- Delegated CX job and handoff reconciliation to the route-independent
  lifecycle orchestrator.
- Persisted the refreshed asynchronous projection only when lifecycle metadata
  changed.
- Returned only the strict `ae_generation_progress.v1` projection; generated
  content and internal orchestration metadata are excluded.
- Normalized CX transport and lifecycle contract failures through the existing
  AE problem response.

## Decisions

- Progress remains explicit polling and does not introduce SSE, token-level
  streaming, or a background poller.
- A terminal local projection is returned without another CX request.
- No database migration, PostgreSQL access, or remote provider is required.

## Verification

```bash
scripts/quality/run_slice_gate.sh --service nex-ae-api \
  --test tests/test_ae_generation_progress_api.py \
  --coverage-target services/nex-ae-api/nex_ae_api/chat.py
```

## Observed Evidence

- Focused API regression: `6 passed`.
- Slice Gate: `2280 passed`, `1 skipped` protected PostgreSQL smoke.
- Repository coverage: statement `97.92%`, branch `95.77%`.
- `chat.py` coverage: statement `97.45%`, branch `97.22%`.
- Contract validation: `98` schemas, `153` examples, `116` negative
  examples, and `7` OpenAPI documents passed.
