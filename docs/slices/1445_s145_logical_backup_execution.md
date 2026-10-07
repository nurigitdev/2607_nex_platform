# Slice 1445: S145 Logical Backup Execution

## Outcome

- Added an atomic PostgreSQL custom-format backup executor.
- Uses only an absolute `pg_dump` binary and a non-secret libpq service name in
  argv; credentials travel through `PGSERVICEFILE` and `PGPASSFILE` in a
  restricted environment.
- Creates mode `0600` partial output, fsyncs it, verifies non-empty content,
  computes SHA-256, and atomically publishes archive and manifest.
- Rejects policy drift, unsafe identifiers, relative credential paths,
  unverified production mounts, duplicate IDs, symlink destinations, empty or
  failed dumps, stale manifest partials, and timezone-naive clocks.

## Evidence Boundary

The public projection includes service/backup identifiers, digest, size,
format, PostgreSQL major, and timestamps. It omits archive paths, credential
paths, subprocess environment, database URLs, users, and row content.

## Handoff

Slice 1446 adds archive inspection and isolated restore guards. A `CREATED`
archive is not yet a verified recovery point.

