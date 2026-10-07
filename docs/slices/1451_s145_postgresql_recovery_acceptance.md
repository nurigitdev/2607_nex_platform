# Slice 1451: S145 PostgreSQL Recovery Acceptance

## Outcome

- Connected to all five real `nex_*_test` databases with their service-local
  roles and used them only for fingerprint queries and `pg_dump`.
- Created five custom-format logical archives through libpq service/pass files;
  no password or database URL appeared in a subprocess argument or evidence.
- Restored all five archives into an ephemeral PostgreSQL 16 cluster and
  verified database identity, migration digest, table count, and required
  extensions before admitting five `VERIFIED` catalog points.
- Captured that isolated cluster with `pg_basebackup`, archived WAL atomically,
  replayed six segments, and paused at the requested recovery timestamp.
- Verified the pre-target probe exists, the post-target probe does not, all
  five database fingerprints still match, and no automatic promotion occurs.

## Compatibility Fixes

The live rehearsal exposed two defects that mock execution could not reveal:

- PostgreSQL passes `RECOVERYXLOG` or `RECOVERYHISTORY` as `%p`; the restore
  adapter now accepts those safe staging names while keeping segment-name and
  destination-parent guards.
- `recovery_target_time` is now rendered as a PostgreSQL timestamp with a
  space separator and UTC offset, rather than RFC3339 `T...Z` syntax.

Both fixes have focused statement and branch coverage at 100%.

## Evidence

- Protected acceptance: 10/10 checks passed.
- Actual databases: 5.
- Migration records: 95.
- Public tables: 121.
- Required extensions: 3 (`pgcrypto` twice and `vector` once).
- Archived WAL segments: 6.
- Measured end-to-end elapsed time: 13.326 seconds.
- Protected pytest: 3 passed, 0 skipped, 13.96 seconds.
- Source residue: marker table absent in all five test databases.
- Runtime residue: zero temporary PostgreSQL processes.

These measurements demonstrate this small test-data rehearsal only. They do
not yet prove the 30/60-minute budgets for production-sized databases.

## Handoff

Slice 1452 publishes the operator runbook and metadata-only attestation,
aggregates all S145 audits, executes Full Gate, and closes S145 without adding
HA, automatic failover, or production deployment approval.
