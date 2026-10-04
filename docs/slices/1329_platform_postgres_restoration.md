# Slice 1329: Platform PostgreSQL durable restoration

## Outcome

- Reused the existing service-owned `service_operational_events` table in all
  five databases; no new table or migration was introduced.
- Added an S133-only, redaction-safe sentinel contract with exact service,
  event type, severity, message, and metadata validation.
- Required separate PostgreSQL connections for write, restore read, cleanup,
  and absence confirmation, proving committed state rather than session-local
  visibility.
- Added partial-write rollback cleanup and final best-effort cleanup without
  exposing database URLs, credentials, event IDs, or private exceptions.

## Decision

The sentinel is temporary operational evidence, not product data. It uses a
unique S133 run identifier, performs no upsert, and must be deleted and proven
absent. A collision therefore fails closed instead of accepting stale evidence.

This Slice proves five-database durability and cleanup using fresh connections.
It does not claim that the full process topology restarted; Slice 1330 composes
the same contract with the Slice 1328 coordinator and all protected processes.

## Verification

- Focused regression: `29 passed, 1 protected skip`; both changed modules
  reached statement and branch coverage `100%`.
- Protected PostgreSQL regression: `9 passed` with no skip against all five
  service-owned test databases.
- Protected restoration smoke: `PASS`; all `89` migrations were current and
  `5` sentinels were restored, deleted, and proven absent through `20` fresh
  PostgreSQL connections.
- Slice Gate: `963 passed, 12 skipped`; statement coverage `98.45%`, branch
  coverage `97.75%`, and all five gate commands passed.
- Contract validation: `156` schemas, `214` examples, `184` negative examples,
  and `7` OpenAPI documents passed.
