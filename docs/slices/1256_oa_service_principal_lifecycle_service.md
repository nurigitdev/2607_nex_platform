# Slice 1256: OA service-principal lifecycle service

## Goal

Expose a persistence-independent principal lifecycle service and wire it into
the OA runtime before adding protected HTTP routes.

## Implementation

- Added principal create/update orchestration over canonical domain planning
  and durable repository writes.
- Added activation and disablement with optimistic revision enforcement.
- Added principal detail and service-filtered list projections.
- Restricted response projections to public principal metadata; repository
  internals are not returned.
- Wired the repository and service into the OA runtime. HTTP routes remain
  intentionally deferred to Slice 1258.

## Verification

```bash
./scripts/quality/run_checkpoint_gate.sh \
  --test tests/test_nex_oa_service_principal_service.py \
  --coverage-target services/nex-oa/nex_oa/service_principal_service.py
```
