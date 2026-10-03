# Slice 1243: OA token surface and mock dependency inventory

## Goal

Inventory every production-source mock token issuer, validator, direct call,
and silent fallback before defining the signed production token profiles.

## Findings

- The shared runtime owns six mock issue/validation functions. Each currently
  has one definition, and their production-source callers are recorded with
  file and line evidence by an AST-based scanner.
- The baseline contains 21 service-token issue calls across 20 modules. Twenty
  are silent `configured token or mock token` fallbacks; the remaining direct
  call is OA's current mock issue route. Two user-token issue calls remain.
- Silent service-token fallback is present in shared transports and outbound
  clients in NeX-AE, NeX-CX, and NeX-AG. NeX-MO is currently a token consumer,
  while NeX-OA is the issuer/session owner and a service-token consumer.
- Mock user tokens are issued in OA session flows and the AE compatibility
  facade. User-token validation is also used by AE, AG, and MO operator-facing
  surfaces.
- OA still exposes explicitly mock service-token and introspection routes in
  both runtime code and OpenAPI. The inventory preserves this honest contract
  until the production profile is implemented in S126.

## Decision

- S125 does not remove the mock symbols. It prohibits silent mock fallback in
  production and preserves compatibility only for an explicit test profile.
- Migration order is shared verifier and OA issuer, then AE, CX, MO, and AG.
- This Slice is read-only: no table, migration, PostgreSQL smoke, or DGX
  provider evidence is required.

## Verification

```bash
./scripts/quality/run_slice_gate.sh \
  --service nex-oa \
  --test tests/test_oa_token_surface_inventory.py \
  --coverage-target scripts/smoke/run_oa_token_surface_inventory.py \
  --smoke scripts/smoke/run_oa_token_surface_inventory.py
```
