# Slice 1013: AE Workspace and Chat Owner-Scope Contract

## Goal

Create one reusable owner-scope contract before changing workspace and chat
routes.

## Implementation

- Added `WorkspaceChatOwnerScope` with canonical tenant, owner, and authority
  fields.
- Browser calls derive owner scope only from the validated OA browser context;
  mismatched payload aliases fail before persistence or provider calls.
- Service calls require explicit tenant and owner identifiers and reject drift
  between canonical ownership refs and compatibility aliases.
- Record visibility compares the persisted tenant/owner pair and fails closed
  for incomplete records.
- API-safe owner summaries include no credential, raw token, private prompt, or
  generated content.

This Slice adds no route mutation, table, migration, or provider call. Workspace
and chat wiring follows in Slices 1016 and 1017.

## Verification

```bash
scripts/quality/run_slice_gate.sh --service nex-ae-api \
  --test tests/test_nex_ae_workspace_chat_auth.py \
  --test tests/test_ae_workspace_chat_owner_scope_contract.py \
  --coverage-target services/nex-ae-api/nex_ae_api/workspace_chat_auth.py \
  --coverage-target scripts/smoke/run_ae_workspace_chat_owner_scope_contract.py \
  --smoke scripts/smoke/run_ae_workspace_chat_owner_scope_contract.py
```

Observed evidence:

- Slice Gate: `1928 passed` with one known warning.
- Repository statement/branch coverage: `97.80%`/`95.49%`.
- Owner-scope module and contract runner statement/branch coverage:
  `100%`/`100%`.
- Contract validation: 92 schemas, 145 positive examples, 109 negative
  examples, and 7 OpenAPI documents.
- Deterministic contract: `PASS`, checks `8/8`, private fields `false`.
