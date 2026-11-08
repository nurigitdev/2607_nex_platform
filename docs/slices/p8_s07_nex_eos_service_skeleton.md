# P8-S07: NeX-EOS Service Skeleton

## Status

Completed on 2026-10-21. NeX-EOS is now an executable Platform service shell
with fail-closed configuration validation, dependency readiness, build
identity, and existing service-trust admission. No EOS business behavior or
database mutation is active.

## Goal

Introduce the NeX-EOS service-owned boundary required by P8 without pulling
P8-S08 database bootstrap or P8-S09 transaction infrastructure forward.

## Implementation

- Added `services/nex-eos/nex_eos` with app, configuration, dependency,
  readiness, and executable entrypoint modules.
- Registered `nex-eos` in the Platform service, authentication, database-env,
  developer-runner, and tiered-quality catalogs. The default endpoint is
  `http://127.0.0.1:8107`.
- Added `NEX_EOS_BASE_URL` and a redacted `NEX_EOS_DATABASE_URL` example.
- Added `contracts/openapi/nex-eos.openapi.yaml` with only root, health,
  readiness, version/build, and protected service-trust routes.
- Reserved `database/nex-eos/` while intentionally adding no migration or
  domain table in this Slice.
- Added EOS as a valid AG signed outbound audience through
  `NEX_AG_TO_EOS_SERVICE_TOKEN`.

## Operations Boundary

The full `SERVICE_SPECS` catalog now includes NeX-EOS so startup, readiness,
service trust, local execution, and quality tooling recognize it. A separate
`SERVICE_RUNTIME_OPERATION_SPECS` catalog preserves the services that already
expose shared Job Control and Service Log APIs.

NeX-EOS does not enter that operations catalog in P8-S07. This prevents AG
from advertising or invoking EOS Job Control and Service Log routes before
those endpoints exist. It may join only in a later Slice that activates and
tests the shared operations surface.

## Database Boundary

The prepared `nex_eos_user`, `nex_eos_dev`, and `nex_eos_test` resources were
not modified. A non-mutating readiness smoke connected to `nex_eos_test` and
read `current_database/current_user`; it did not create or alter data. No
migration, table creation, persistence runtime, or JobQueue ran in P8-S07.
P8-S08 owns those actions.

## Verification

- EOS focused tests: `18 passed`.
- EOS Slice Gate: passed all three commands.
- EOS bounded coverage: statement `100%`, branch `100%` against minimums of
  `95%` and `94%`.
- Related runtime, AG operations, readiness, developer tooling, and contract
  regression: `458 passed`.
- Actual PostgreSQL readiness smoke: HTTP `200`, status `READY`, database
  `nex_eos_test`, role `nex_eos_user`.
- Contract validation: 174 schemas, 236 examples, 204 negative examples, and
  9 OpenAPI documents.
- `git diff --check`: passed.
- Platform Full Gate: not repeated; P8.1 closed with a successful Full Gate at
  P8-S06, and P8-S07 follows the Slice Gate cadence.

## Exit Decision

P8-S07 is closed. P8-S08 may register NeX-EOS dev/test database profiles,
create the migration baseline, and verify fresh/re-run/error/reset behavior
against the prepared PostgreSQL databases.
