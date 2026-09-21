# Slice 0918: CX API contract ownership hardening

## Goal

Make authenticated owner context mandatory and consistent across private CX APIs,
then propagate the same context from AE callers without exposing private content.

## Decision

- CX accepts trusted service authentication plus `X-NEX-Tenant-ID` and
  `X-NEX-Subject-ID` as the canonical owner transport.
- Payload or query owner aliases are assertions only. When present, they must
  match the authenticated context.
- Missing or invalid owner context fails closed. A cross-owner resource read is
  exposed as `404`, not `403`, to avoid confirming resource existence.
- Retrieval, generation, processing, and derived-content records carry the
  canonical owner lineage established in Slice 0917.
- AE CX clients propagate owner context from canonical ownership data, actor
  claims, or established local defaults for legacy local-only paths.

## Contract hardening

- `contracts/openapi/nex-cx.openapi.yaml` is versioned `0.92.0` and declares the
  two owner headers on private CX operations.
- All 29 CX runtime operations are represented by the OpenAPI inventory.
- The CX negative-fixture inventory covers all 11 CX service schemas.
- The source ownership decision fixture now has a fail-closed missing-status
  case.

## Verification

Run:

```bash
./.venv/bin/pytest -q tests/test_nex_cx_api_ownership.py \
  tests/test_nex_ae_cx_owner_context.py \
  tests/test_cx_api_contract_ownership_hardening.py
./.venv/bin/python scripts/smoke/run_cx_api_contract_ownership_hardening.py --summary
```

PostgreSQL ownership enforcement is exercised separately in Slice 0919. DGX
Spark and model providers are not required for this contract slice.

