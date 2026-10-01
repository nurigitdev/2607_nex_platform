# Slice 1217: OA membership lifecycle service API

## Goal

Expose revisioned direct membership transitions through the same protected OA
lifecycle service boundary as subject transitions.

## Behavior

- The membership route is scoped by tenant and subject and requires
  `service:call` plus `identity:lifecycle:write`.
- Actor, request, and trace identity are derived by the server.
- Membership disable and re-enable preserve revision and reason lineage.
- A disabled membership reports session invalidation intent. Atomic revocation
  execution is introduced in Slice 1218.
- Existing membership ensure and read behavior remains compatible.

## Verification

```bash
./scripts/quality/run_slice_gate.sh \
  --service nex-oa \
  --test tests/test_nex_oa_identity_lifecycle_service.py \
  --test tests/test_oa_membership_lifecycle_api.py \
  --coverage-target services/nex-oa/nex_oa/identity_lifecycle_service.py \
  --coverage-target scripts/smoke/run_oa_membership_lifecycle_api.py \
  --smoke scripts/smoke/run_oa_membership_lifecycle_api.py
```
