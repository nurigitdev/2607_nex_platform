# Slice 1276: CX signed-token verification adoption

## Goal

Adopt the shared signed service-token admission runtime at the NeX-CX owner
boundary and remove silent mock fallback from CX-to-MO calls.

## Implementation

- Wired the CX application to an audience-bound shared admission runtime.
- Preserved the central access-context boundary while allowing it to consume
  locally verified signed claims from application state.
- Kept direct helper calls and test-built applications compatible with the
  explicit `TEST_MOCK` profile.
- Centralized CX outbound token selection for embedding, generation, and
  reranking. `DUAL_READ` and `SIGNED_ONLY` now require
  `NEX_CX_TO_MO_SERVICE_TOKEN` and fail closed when it is absent.
- Added privacy-safe signed-token adoption evidence. No raw token is projected.

No database migration or DGX provider is required.

## Verification

```bash
./scripts/quality/run_slice_gate.sh \
  --service nex-cx \
  --test tests/test_nex_cx_service_token_adoption.py \
  --test tests/test_cx_signed_token_adoption_smoke.py \
  --coverage-target scripts/smoke/run_cx_signed_token_adoption.py \
  --smoke scripts/smoke/run_cx_signed_token_adoption.py

./scripts/quality/run_checkpoint_gate.sh \
  --test tests/test_nex_cx_service_token_adoption.py \
  --test tests/test_cx_signed_token_adoption_smoke.py \
  --smoke scripts/smoke/run_cx_signed_token_adoption.py
```
