# Slice 1418: Platform Packaged Deployment Lifecycle

## Outcome

- Bound all thirteen packaged process entrypoints to the existing six-layer
  dependency graph for each runtime profile.
- Added service-owned pre-start migrations in OA, MO, CX, AE, AG order for
  persistent profiles; `local_mock` performs no PostgreSQL migration.
- Selected liveness only for local mock HTTP processes, readiness for every
  protected HTTP process, and two live-process observations for background
  roles.
- Defined exact reverse-order stop and deterministic restart phases.
- Required rollback to select a complete previous six-artifact set and verify
  compatibility with the current database schema.

## Rollback Decision

Artifact rollback and database downgrade are separate operations. S142 permits
only a complete artifact-set rollback; mixed current/previous artifacts and
automatic database downgrade are prohibited. A previous artifact set may start
only after schema compatibility is verified. Slice 1419 will assign immutable
identities to the current and previous complete sets.

The plan is metadata-only. It contains packaged commands, environment variable
names, probe paths, and artifact IDs but no database URL, token, provider key,
image reference, or production endpoint value. Production contact and
deployment approval remain disabled.

## Verification

- Focused tests: `9 passed`; lifecycle domain and smoke runner statement and
  branch coverage are both `100%`.
- Lifecycle smoke: five profiles, `65` process steps, `20` migration steps,
  six artifacts per complete set, and three blocked live profiles; no database,
  provider, registry, or production resource was contacted.
- Slice Gate: `977 passed, 11 skipped`; statement coverage `98.45%`; branch
  coverage `97.82%`; smoke-runner statement and branch coverage `100%`;
  contract validation `166` schemas, `228` examples, `196` negative examples,
  and `7` OpenAPI documents.
