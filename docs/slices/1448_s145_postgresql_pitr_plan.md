# Slice 1448: S145 PostgreSQL PITR Plan

## Outcome

- Added a credential-safe `pg_basebackup` plan using the dedicated
  `nex-platform-cluster-backup` libpq service, streamed WAL, fast checkpoint,
  and SHA-256 backup manifest.
- Added atomic WAL archive and restore commands with strict segment names,
  mode-0600 files, collision denial, idempotency, digest sidecars, and copy
  verification.
- Froze five-minute archive timeout, latest timeline recovery, and
  `recovery_target_action=pause`.
- Cutover cannot proceed until timeline, all five databases, migration heads,
  and an explicit operator decision are verified. Automatic promotion remains
  disabled.

## Handoff

Slice 1449 makes logical/base-backup execution restart-safe with an exclusive
lock, durable state, bounded retry, and stale-run recovery.
