# Slice 1017: AE Owner-Scoped Chat Persistence API

## Goal

Apply the shared owner boundary to chat interactions and make the existing
workspace lineage column part of durable chat persistence and readback.

## Implementation

- Chat routes now use the shared AE facade authorization boundary for service
  and browser user claims.
- Browser create requests derive tenant and user identifiers from authenticated
  OA claims. Conflicting payload identifiers are rejected before CX calls.
- Browser detail and artifact-link routes use owner-filtered repository reads;
  missing and cross-owner interactions return the same not-found response.
- Memory and SQL stores expose `get_for_owner`. The SQL implementation includes
  tenant and user predicates in the interaction query instead of loading a
  cross-owner row and filtering it after materialization.
- Chat records now carry canonical `owner_user_id` plus the compatibility
  `user_id`, and preserve nullable `workspace_id` through upsert and restart
  readback.
- The selected chat store is exposed on `app.state.ae_chat_store` for the
  workspace-bound orchestration Slice.
- Existing service-call local defaults remain supported for compatibility;
  explicit service owner identifiers still pass through canonical consistency
  checks.
- S101 live audits now mark workspace and chat ownership as hardened while the
  artifact-file delivery boundary remains explicitly tracked.

This Slice uses deterministic memory and SQLite regression evidence. Actual
`nex_ae_test` migration and owner-isolation proof remains Slice 1020 work.

## Verification

```bash
scripts/quality/run_slice_gate.sh --service nex-ae-api \
  --test tests/test_nex_ae_chat.py \
  --test tests/test_ae_owner_scoped_chat_api.py \
  --coverage-target services/nex-ae-api/nex_ae_api/chat.py \
  --coverage-target scripts/smoke/run_ae_owner_scoped_chat_api.py \
  --smoke scripts/smoke/run_ae_owner_scoped_chat_api.py
```

Observed evidence:

- Focused chat, analytics, audit, and closure regression: `91 passed`.
- Slice Gate: `1952 passed` with one known Starlette warning.
- Statement/branch coverage: `97.76%`/`95.53%`.
- Chat module statement/branch coverage: `97.96%`/`98.12%`.
- Smoke runner statement/branch coverage: `100%`/`100%`.
- Contract validation: 92 schemas, 145 positive examples, 109 negative
  examples, and 7 OpenAPI documents.
- Deterministic smoke: checks `10/10`, one owner-scoped interaction, workspace
  lineage retained, cross-owner interaction and artifact-link reads hidden.
