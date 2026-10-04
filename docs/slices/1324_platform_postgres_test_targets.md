# Slice 1324: Platform PostgreSQL test targets

## Outcome

- Added one canonical service-to-test-database target registry for OA, MO, CX,
  AE, and AG.
- Validated PostgreSQL driver, expected database name, expected service-owned
  role, distinct service-local URLs, and placeholder rejection.
- Mapped protected `test` profile URLs into the active database environment
  names consumed by service runtimes without exposing values in projections.
- Preserved optional CX vector database separation through an explicit test to
  active environment alias.

## Decision

`NEX_*_TEST_DATABASE_URL` remains the operator-facing test configuration. A
child process receives the matching `NEX_*_DATABASE_URL` alias only after the
target passes service ownership validation. Production database names and
roles cannot satisfy this boundary.

## Verification

- Focused regression: `24 passed`; exact statement/branch coverage: `100%/100%`
  for target resolution, child environment mapping, and the smoke runner.
- Slice Gate: `958 passed`, `11 skipped`; aggregate statement coverage `98.44%`
  and branch coverage `97.75%`.
- Contract validation: `156` schemas, `214` examples, `184` negative examples,
  and `7` OpenAPI documents passed.
- Synthetic URLs exercise configuration only; no database connection or data
  mutation occurs in this Slice.
