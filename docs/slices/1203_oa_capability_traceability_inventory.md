# Slice 1203: OA capability traceability inventory

## Goal

Map every `OA-FR-001` through `OA-FR-005` requirement to current repository
implementation, tests, and operational evidence without treating traceability as
feature acceptance.

## Result

- All five requirements have complete requirement, implementation, test, and
  operations evidence layers.
- `OA-FR-001` is implemented for the current employee-id/password MVP boundary.
- `OA-FR-002` is partial because durable user sessions coexist with unsigned
  mock service-token issuance.
- `OA-FR-003` is partial because user-session introspection exists but a
  production service-token introspection or JWKS path does not.
- `OA-FR-004` is partial because user role/scope and service identity claims
  exist, but group claim references do not.
- `OA-FR-005` is partial because a durable redacted operational-event substrate
  exists, but login/session-specific audit emission is not wired.
- The four partial capabilities are explicit S122+ inputs; they do not make the
  S121 inventory itself incomplete.
- No table or migration is added.

## Verification

```bash
./.venv/bin/python \
  scripts/smoke/run_oa_capability_traceability_inventory.py --summary

./scripts/quality/run_slice_gate.sh \
  --service nex-oa \
  --test tests/test_oa_capability_traceability_inventory.py \
  --coverage-target services/nex-oa/nex_oa/current_state_traceability.py \
  --coverage-target scripts/smoke/run_oa_capability_traceability_inventory.py \
  --smoke scripts/smoke/run_oa_capability_traceability_inventory.py
```
