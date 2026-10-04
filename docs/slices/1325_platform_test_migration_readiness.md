# Slice 1325: Platform test migration readiness

## Outcome

- Composed the existing service migration runner in deterministic OA, MO, CX,
  AE, and AG startup order.
- Required database/role identity, complete migration ledger equality, and a
  successful `SELECT 1` before protected startup can be allowed.
- Added normalized, privacy-safe failure codes and typed S133 migration and
  readiness evidence.
- Added a protected runner for actual five-test-database execution.

## Decision

Migration and database readiness are a hard startup prerequisite. The runtime
must not spawn any service process when one database is missing, owned by the
wrong role, behind or ahead of the repository migration ledger, or cannot
complete a basic query.

## Verification

- Focused regression: `13 passed`, `1 protected skip`; exact statement/branch
  coverage: `100%/100%` for orchestration and smoke runner.
- Protected actual PostgreSQL regression: `14 passed` with no skip.
- Actual five-test-database result: `PASS`, `5` services, `89` current
  migrations, `0` newly applied, and all identity/readiness/ledger checks
  passed.
- Slice Gate: `947 passed`, `12 skipped`; aggregate statement coverage `98.44%`
  and branch coverage `97.74%`.
- Contract validation: `156` schemas, `214` examples, `184` negative examples,
  and `7` OpenAPI documents passed.
