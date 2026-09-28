# Slice 1063: AE Private Generated-Response Storage

## Goal

Add a private AE storage boundary for owner-visible generated response content
without placing raw response text in PostgreSQL or exposing local paths.

## Implementation

- Added deterministic payload metadata with SHA-256, UTF-8 byte size, content
  type, response ID, and logical `ae://chat-responses/...` reference.
- Added in-memory storage for deterministic tests and local filesystem storage
  selected by `NEX_AE_CHAT_RESPONSE_STORAGE_ROOT`.
- Local writes use a same-directory temporary file, `fsync`, atomic replace,
  and `0600` file permissions.
- Every read validates UTF-8 decoding, byte size, and SHA-256 before returning
  content. Invalid references, path traversal, tampering, and I/O failures fail
  closed with safe error codes.
- Public metadata can omit `content`; no method returns the backing filesystem
  path as an API value.

## Operating Configuration

```bash
NEX_AE_CHAT_RESPONSE_STORAGE_ROOT=/data/nex-platform/ae/chat-responses
```

The default remains in-memory until the environment variable is configured.
Tests and protected smoke use temporary directories.

## Verification

```bash
scripts/quality/run_slice_gate.sh --service nex-ae-api \
  --test tests/test_nex_ae_generated_response_storage.py \
  --coverage-target services/nex-ae-api/nex_ae_api/generated_response_storage.py \
  --smoke scripts/smoke/run_ae_generated_response_lineage_boundary_audit.py
```

## Observed Evidence

- Slice Gate: `2428 passed`, `3 skipped` protected PostgreSQL tests.
- Coverage: statement `97.97%`, branch `95.89%`.
- Storage module coverage: statement `100.00%`, branch `100.00%`.
- Contracts: schemas `101`, examples `159`, negative examples `122`,
  OpenAPI documents `7`.
- Boundary progress: gaps `8`, open `7`, next `1064`.
