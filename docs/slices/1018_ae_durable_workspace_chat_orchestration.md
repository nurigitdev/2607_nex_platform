# Slice 1018: AE Durable Workspace Chat Orchestration

## Goal

Turn workspace-bound chat into one owner-checked, restart-readable, idempotent
lifecycle without moving provider or retrieval responsibilities into AE.

## Implementation

- Added a focused orchestration module outside the already-large chat runtime.
- Workspace-bound admission verifies workspace existence, tenant/user ownership,
  and `chat_document_id` before retrieval or generation calls. Cross-owner
  workspace access is indistinguishable from a missing workspace.
- Missing `chat_document_id` is derived from the workspace; a conflicting value
  is rejected before provider work.
- A metadata-only PENDING chat record is persisted before retrieval or generation.
  Completion, no-answer, quality rejection, and provider failure then upsert a
  terminal record while preserving the original creation timestamp.
- Provider and retrieval failures retain only safe error code, retryability, and
  stage metadata. Raw provider details are not persisted.
- Workspace activity records capture started, completed, no-answer, or failed
  lifecycle states using interaction id and message hash, never raw prompt text.
- Exact interaction retries return the existing record without another provider
  call or duplicate activity. Reusing an interaction id for different input,
  workspace, or chat document fails closed.
- Legacy chat without `workspace_id` remains supported and receives deterministic
  interaction and chat-document identities.

This Slice uses memory and SQLite regression evidence. Actual PostgreSQL
transaction and restart proof remains scheduled for Slice 1020; remote model
providers are not required for this orchestration boundary.

## Verification

```bash
scripts/quality/run_slice_gate.sh --service nex-ae-api \
  --test tests/test_nex_ae_workspace_chat_orchestration.py \
  --test tests/test_nex_ae_chat.py \
  --test tests/test_ae_durable_workspace_chat_orchestration.py \
  --coverage-target services/nex-ae-api/nex_ae_api/workspace_chat_orchestration.py \
  --coverage-target services/nex-ae-api/nex_ae_api/chat.py \
  --coverage-target scripts/smoke/run_ae_durable_workspace_chat_orchestration.py \
  --smoke scripts/smoke/run_ae_durable_workspace_chat_orchestration.py
```

Observed evidence:

- Focused orchestration and chat regression: `75 passed` before the final branch
  additions; final focused coverage run: `61 passed`.
- Slice Gate: `1966 passed` with one known Starlette warning.
- Statement/branch coverage: `97.74%`/`95.56%`.
- Final orchestration module statement/branch coverage: `100%`/`100%`.
- Chat module statement/branch coverage: `97.59%`/`98.78%`.
- Deterministic smoke runner statement/branch coverage: `100%`/`100%`.
- Contract validation: 92 schemas, 145 positive examples, 109 negative
  examples, and 7 OpenAPI documents.
- Deterministic smoke: checks `12/12`, one provider call across two identical
  requests, three ordered workspace activities, and cross-owner admission hidden.
