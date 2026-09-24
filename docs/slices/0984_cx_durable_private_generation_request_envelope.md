# Slice 0984: CX Durable Private Generation Request Envelope

## Goal

Persist asynchronous generation inputs without placing prompt or evidence text
in `service_jobs`.

## Result

- Added immutable owner-private `generation_request` payload support.
- Canonical JSON envelopes bind source payload, MO payload, compatibility rule,
  retrieval package, admission, generation, request, trace, tenant, and owner.
- Receipts expose only backend/URI, SHA-256, and UTF-8 byte size.
- Restart reload verifies owner scope, generation identity, hash, size, schema,
  JSON validity, and MO generation binding.
- Credential-like keys are rejected recursively.
- Default root is `/data/nex-platform/cx/generation-requests`, configurable with
  `NEX_CX_GENERATION_REQUEST_STORAGE_ROOT`.

No database table or remote provider is required.

## Verification

```bash
./.venv/bin/pytest -q tests/test_nex_cx_generation_request_store.py \
  tests/test_nex_cx_private_content.py \
  --cov=nex_cx.generation_request_store --cov-branch \
  --cov-report=term-missing
```
