# Slice 1327: Platform test profile startup

## Outcome

- Enabled the seven background process shells for the protected `test` profile
  with service-owned PostgreSQL worker pools.
- Kept background work claiming disabled while requiring module import, worker
  pool query readiness, stable process startup, and pool disposal.
- Added protected startup evidence for five APIs and seven workers/daemons
  after the five-database migration/readiness prerequisite.
- Kept AE Web, remote model providers, and business work execution outside this
  Slice.

## Decision

S133 proves process and persistence lifecycle only. Synthetic signed-token
configuration is admitted solely for startup because no protected business
route is invoked; signed trust behavior remains the completed S128-S130 scope
and is not re-claimed here.

## Verification

- Focused regression: `20 passed, 1 protected skip`; both changed scripts
  reached statement and branch coverage `100%`.
- Protected PostgreSQL regression: `9 passed` with no skip against all five
  service-owned test databases.
- Protected startup smoke: `PASS`; all `89` migrations were current, five
  APIs and seven worker/daemon shells reached readiness (`12/12`).
- Slice Gate: `954 passed, 12 skipped`; statement coverage `98.47%`, branch
  coverage `97.79%`, and all five gate commands passed.
- Contract validation: `156` schemas, `214` examples, `184` negative examples,
  and `7` OpenAPI documents passed.
