# Slice 1330: Platform PostgreSQL protected restart smoke

## Outcome

- Composed the S133 migration gate, ten API/worker pools, thirteen-process test
  topology, coordinated restart state machine, and five-database restoration
  contract into one protected smoke.
- Required two complete migration/readiness passes, two process generations,
  ten fresh second-generation engine identities, and one restart.
- Wrote the five durable sentinels only after generation 1 was ready, restored
  them only after generation 2 was ready, then stopped all processes before
  cleanup and absence confirmation.
- Emitted `60` typed, privacy-safe evidence records covering configuration,
  migration, pool readiness, startup, shutdown, restart, restoration, and
  cleanup for every service.

## Decision

This is a protected integration smoke and requires all five service-owned test
database URLs. It never admits a development or production database. Synthetic
signed-trust values are used only because no protected business route is
called; trust activation remains S134.

Background shells do not claim jobs and no remote embedding, reranking, or
generation provider is contacted. The smoke validates process and persistence
lifecycle, not business workflow execution.

## Verification

- Mocked orchestration regression: `8 passed, 1 protected skip`; the changed
  smoke module reached statement and branch coverage `100%`.
- Protected PostgreSQL/process regression: `9 passed` with no skip against all
  five service-owned test databases.
- Protected restart smoke: `PASS`; all `89` migrations were current in both
  gates, `13` processes reached readiness in each of two generations, `10+10`
  pool identities were fresh, and all `5` sentinels were restored and cleaned.
- Post-smoke process inspection found no remaining API, Web, worker, or daemon
  process; direct counts confirmed zero S133 sentinel rows in each of the five
  test databases.
- Slice Gate: `942 passed, 12 skipped`; statement coverage `98.44%`, branch
  coverage `97.75%`, and all five gate commands passed.
- Contract validation: `156` schemas, `214` examples, `184` negative examples,
  and `7` OpenAPI documents passed.
