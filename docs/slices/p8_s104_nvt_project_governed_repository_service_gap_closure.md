# P8-S104: NVTProject Governed Repository/Service Gap Closure

## Scope

P8-S104 closes the EOS-owned NVTProject persistence and domain gaps required
before the governed authorization and HTTP surface is added in P8-S105.

- `create_nvt_project_in_session()` allows a future governed BusinessOperation
  to create an NVTProject in the same transaction as idempotency and outbox
  state.
- tenant-scoped LIST supports `status`, bounded `limit`, and non-negative
  `offset`, ordered by `nvt_project_code ASC, nvt_project_id ASC`.
- `update_nvt_project_in_session()` locks the current row, enforces optimistic
  versioning, and changes only `name` and `status`.
- an exact no-change request preserves the existing version and timestamp.
- ACTIVE to INACTIVE is rejected with `EOS_NVT_PROJECT_IN_USE` while an ACTIVE
  Mother Project directly references the NVTProject.
- INACTIVE to ACTIVE and NVTProject updates without active Mother Projects
  remain admitted.

The existing `eos_nvt_project` and `eos_project` tables are sufficient. This
Slice adds no table, migration, direct cross-service database read, API route,
OA scope, or NSL artifact. Those governed surfaces remain assigned to P8-S105
and P8-S106.

## Regression Alignment

The earlier P8-S12 hierarchy regression deactivated an NVTProject after an
ACTIVE Mother Project had been created. CA05 intentionally forbids that state,
so the regression now uses a separate NVTProject that is made INACTIVE before
checking that new Mother Project creation fails closed.

## Verification

- focused NVT/hierarchy regression: `39 passed`
- focused project operation regression: `53 passed`, one dependency warning
- Ruff: passed for the changed source and tests
- EOS Slice Gate: `680 passed`, `21` expected protected skips
- EOS statement coverage: `98.79%`
- EOS branch coverage: `97.96%`
- contract validation: `197` schemas, `261` examples, `224` negative examples,
  and `9` OpenAPI documents

The protected skips are pre-existing opt-in PostgreSQL profiles. P8-S104 does
not change DDL; focused PostgreSQL concurrency is owned by P8-S109 and the
actual multi-service protected acceptance is owned by P8-S112.

## Exit

P8-S104 is complete. P8-S105 may now add the fresh-OA protected NVTProject
CREATE/GET/LIST/UPDATE service and API boundary without changing persistence
shape.
