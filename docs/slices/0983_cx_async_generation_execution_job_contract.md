# Slice 0983: CX Asynchronous Generation Execution Job Contract

## Goal

Define a deterministic, metadata-only job contract for asynchronous grounded
generation before adding storage or execution behavior.

## Result

- Job type: `cx.grounded-generation.execute`.
- Job ID and idempotency key derive deterministically from `cx_generation_id`.
- The payload carries only owner identifiers, admission/generation identifiers,
  and immutable private-envelope integrity metadata.
- Prompt, evidence text, output text, request bodies, and credentials are
  rejected recursively.
- Owner projections omit internal payload and error detail.
- Default retry budget is three attempts and remains compatible with the S98
  worker retry/dead-letter policy.

No database table or remote provider is required by this Slice.

## Verification

```bash
./.venv/bin/pytest -q tests/test_nex_cx_async_generation_contracts.py \
  --cov=nex_cx.async_generation_contracts --cov-branch \
  --cov-report=term-missing
```
