# Slice 1253: OA service-principal domain contracts

## Goal

Define fail-closed, persistence-independent contracts for service principals
and client credentials before creating database tables.

## Implementation

- Added canonical principal, credential, service ID, audience, scope, status,
  lifetime, and revision normalization.
- Added principal create/update planning with immutable identity and optimistic
  revision checks.
- Added credential issue planning with active-principal enforcement, a 90-day
  maximum lifetime, and a maximum of two simultaneous active credentials.
- Added credential transition planning for rotation, revocation, and expiry,
  including a maximum 24-hour rotation grace period and terminal-state guards.
- Kept secret generation, hashing, persistence, and APIs outside this Slice.

## Verification

```bash
./scripts/quality/run_slice_gate.sh \
  --service nex-oa \
  --test tests/test_nex_oa_service_principals.py \
  --coverage-target services/nex-oa/nex_oa/service_principals.py
```
