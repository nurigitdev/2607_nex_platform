# P7-S2 - AE CA/PA/EA Agent Registry Runtime

## Status

COMPLETED

## Implemented

- generalized the existing `ae_agent_identity` repository for CA/PA/EA;
- preserved project-neutral IA provisioning and assignment behavior;
- added registration, tenant-scoped lookup, bounded candidate listing, status
  transition, and exact active-PA resolution;
- enforced one active PA per tenant/project with a PostgreSQL partial unique
  index and typed conflict handling;
- exposed protected internal registry APIs for AG writes and WC metadata reads;
- kept credentials, prompts, DB sessions, and mutable authorization grants out
  of registry projections;
- updated the AE OpenAPI contract.

## Boundary

Agent registration and status are AE-owned identity lifecycle operations.
Registry metadata is not routing or claim authority. WC receives only bounded
identity projections and must perform a fresh OA authorization check in S3.

## Verification

- focused IA + background registry tests: `24 passed`;
- actual `nex_ae_test` PostgreSQL smoke: `1 passed`;
- migration `2400_ae_background_agent_registry` applied;
- PostgreSQL restart lookup, active PA uniqueness, cleanup, and zero residue PASS;
- changed-source statement/branch coverage: `98.02%`;
- related execution/foundation/CA01/migration regression: `74 passed`;
- contract validation: PASS, including `8` OpenAPI documents.

## Next

P7-S3 may consume these projections for deterministic exact eligibility and
commit WC Assignment/Claim/lease state atomically.
